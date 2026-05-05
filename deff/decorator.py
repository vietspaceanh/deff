from __future__ import annotations

import contextvars
import functools
import inspect
import types
import typing

from .runtime import runtime
from .specs import Query, TableSpec, sanitize_alias
from .table import Table, func_refs

composition_deps: contextvars.ContextVar[tuple[list, ...]] = contextvars.ContextVar(
    "composition_deps", default=()
)
    

def tbl(func) -> Table:
    tf = TableFunction(func)
    functools.update_wrapper(tf, func)
    return typing.cast(Table, tf)


class TableFunction:
    def __init__(self, func=None):
        self.func = func
        if func is not None:
            self._init_from_func(func)

    def _init_from_func(self, func):
        self.func = func
        self.name = _qualified_name(func)
        self._cached_table: Table | None = None
        self._cached_fingerprint: int | None = None
        self._global_deps = _global_deps(func)

        stack = composition_deps.get()
        self.is_local = bool(stack)
        self._depth = len(stack)

        if not self.is_local:
            runtime.register(self.name, self)

    def __call__(self, *args, **kwargs):
        if self.func is None:
            self._init_from_func(args[0])
            return self

        sig = inspect.signature(self.func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        all_args = dict(bound.arguments)

        # Cache check (module-level tables only)
        if not self.is_local:
            default_kwargs = self.args
            is_default_call = default_kwargs is not None and not args and all_args == default_kwargs
            if is_default_call and self._cached_table is not None and self._cached_fingerprint == self._dependency_fingerprint():
                return self._cached_table
        else:
            is_default_call = False

        # Run function (captures local dep tables and f-string refs)
        local_deps: list[Table] = []
        token = composition_deps.set(composition_deps.get() + (local_deps,))
        fstring_refs: set[str] = set()
        refs_token = func_refs.set(fstring_refs)
        try:
            result = self.func(*args, **kwargs)
        finally:
            func_refs.reset(refs_token)
            composition_deps.reset(token)

        # Resolve references among deps
        raw_sql = f"SELECT * FROM {result}" if isinstance(result, Table) else result
        if isinstance(result, Table):
            fstring_refs.add(result.name)
        query = Query(raw_sql, func_name=self.func.__name__)
        _validate_bare_refs(query, fstring_refs)
        referenced = query.table_names

        for val in all_args.values():
            if isinstance(val, Table):
                local_deps.append(val)

        local_deps = [d for d in local_deps if d.name in referenced]

        # Build spec and table
        name = sanitize_alias(self.name, all_args)

        spec = TableSpec(
            query=query,
            func_name=self.name,
            name=name,
            args=all_args,
            deps=[d.spec for d in local_deps if not d.is_cte],
            ctes=[d.spec for d in local_deps if d.is_cte],
            is_cte=self.is_local,
        )

        table = Table(spec)

        # Register alias and update cache
        if not self.is_local:
            self._last_args = all_args
            if table.name != self.name:
                runtime.register(table.name, spec)
            if is_default_call:
                self._cached_table = table
                self._cached_fingerprint = self._dependency_fingerprint()

        # Stack to parent's composition deps
        stack = composition_deps.get()
        if stack:
            stack[-1].append(table)

        return table

    @property
    def args(self) -> dict | None:
        sig = inspect.signature(self.func)
        try:
            bound = sig.bind()
            bound.apply_defaults()
            return dict(bound.arguments)
        except TypeError:
            return None

    def __format__(self, format_spec):
        if self.args is None:
            raise ValueError(
                f"Table '{self.name}' requires explicit arguments "
                f"and cannot be used in f-strings."
            )
        name = self().name
        ctx = func_refs.get()
        if ctx is not None:
            ctx.add(name)
        return name

    def __str__(self):
        if self.is_local:
            if self._cached_table is None:
                self._cached_table = self()
            stack = composition_deps.get()
            if stack:
                target = stack[self._depth - 1]
                if not any(d is self._cached_table for d in target):
                    target.append(self._cached_table)
            return self._cached_table.name

        if self.args is None:
            raise RuntimeError(
                f"'{self.__name__}' table requires parameters. "
                f"Call {self.__name__}(...) and/or assign the result to a variable to use."
            )

        return self().name

    def _dependency_fingerprint(self) -> int:
        g = self.func.__globals__
        parts = []
        for name in self._global_deps:
            val = g[name]
            if isinstance(val, TableFunction):
                t = val() if val.args is not None else None
                parts.append(f"{name}={t.spec.sql if t else None}")
            elif isinstance(val, types.ModuleType):
                parts.append(f"{name}={val.__name__}")
            elif hasattr(val, '__dict__'):
                parts.append(f"{name}={sorted(val.__dict__.items())}")
            else:
                parts.append(f"{name}={val!r}")
        return hash("|".join(parts))

    def __getattr__(self, name):
        if self.args is None:
            raise AttributeError(
                f"You seem to access an un-initialized table (on attribute '{name}'). "
                f"This table requires explicit arguments and cannot be called implicitly."
            )
        return getattr(self(), name)

    def __repr__(self):
        if self.args is None:
            return f"Table({self.name}) (uninitialized)"
        return f"Table({self.name}({self.args}))"

    def _repr_html_(self):
        return self.__getattr__('_repr_html_')()

    def __rich_console__(self, console, options):
        return self().__rich_console__(console, options)

    def __getitem__(self, cols: str):
        return self.__getattr__('__getitem__')(cols)

    def __or__(self, query: str):
        return self.__getattr__('__or__')(query)


def _qualified_name(func) -> str:
    module = func.__module__.rsplit(".", 1)[-1]
    if module == "__main__" or module == "__mp_main__":
        return f"_main__{func.__name__}"
    return f"{module}__{func.__name__}"


def _global_deps(func):
    names = set()
    stack = [func.__code__]
    while stack:
        c = stack.pop()
        for x in c.co_consts:
            if isinstance(x, types.CodeType):
                stack.append(x)
        names.update(n for n in c.co_names if n in func.__globals__)
    return names


def _validate_bare_refs(query: Query, fstring_refs: set[str]) -> None:
    """Make sure the table refs in query are functions, not bare strings."""
    refs_in_sql = query.table_references
    known_names = {ref.split("__", 1)[-1] for ref in fstring_refs if ref}
    registered_bare = {k.split("__", 1)[-1] for k in runtime.tables}
    all_known = known_names | registered_bare
    bare_in_sql = refs_in_sql - fstring_refs
    invalid = [n for n in bare_in_sql if n in all_known]
    if invalid:
        msg = "; ".join(
            f"Table '{n}' in function '{query.func_name}' was referenced as a raw string. "
            f"Use f'...{{{n}}}...' to reference by variable."
            for n in invalid
        )
        raise ValueError(msg)