from __future__ import annotations

import contextvars
import inspect

from .specs import TABLE_DEFS, TableSpec, clean_sql, extract_table_names, sanitize_alias
from .table import Table

composition_deps: contextvars.ContextVar[tuple[list, ...]] = contextvars.ContextVar(
    "composition_deps", default=()
)


def _qualified_name(func) -> str:
    module = func.__module__.rsplit(".", 1)[-1]
    if module == "__main__":
        return func.__name__
    return f"{module}__{func.__name__}"


class tbl:
    def __init__(self, func):
        self._func = func
        self.name = _qualified_name(func)
        self._cached_table: Table | None = None
        self.__wrapped__ = func
        self.__name__ = func.__name__
        self.__doc__ = func.__doc__

        stack = composition_deps.get()
        self.is_local = bool(stack)

        if not self.is_local:
            TABLE_DEFS[self.name] = self

    def __call__(self, *args, **kwargs):
        sig = inspect.signature(self._func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        all_args = dict(bound.arguments)

        local_deps: list[Table] = []
        token = composition_deps.set(composition_deps.get() + (local_deps,))
        try:
            sql = self._func(*args, **kwargs)
        finally:
            composition_deps.reset(token)

        referenced = extract_table_names(clean_sql(sql))

        for val in all_args.values():
            if isinstance(val, Table):
                local_deps.append(val)

        local_deps = [d for d in local_deps if d.name in referenced]

        name = sanitize_alias(self.name, all_args)

        spec = TableSpec(
            sql=clean_sql(sql),
            func_name=self.name,
            name=name,
            args=all_args,
            deps=[d.spec for d in local_deps if not d.is_cte],
            ctes=[d.spec for d in local_deps if d.is_cte],
            is_cte=self.is_local,
        )

        table = Table(spec)

        if not self.is_local:
            self._last_args = all_args
            if table.name != self.name:
                TABLE_DEFS[table.name] = spec

        stack = composition_deps.get()
        if stack:
            stack[-1].append(table)

        return table

    def get_default_kwargs(self) -> dict | None:
        sig = inspect.signature(self._func)
        try:
            bound = sig.bind()
            bound.apply_defaults()
            return dict(bound.arguments)
        except TypeError:
            return None

    def __str__(self):
        if self.is_local:
            if self._cached_table is None:
                self._cached_table = self()
            stack = composition_deps.get()
            if stack and not any(d is self._cached_table for d in stack[-1]):
                stack[-1].append(self._cached_table)
            return self._cached_table.name

        if self.get_default_kwargs() is None:
            raise RuntimeError(
                f"'{self.__name__}' table requires parameters. "
                f"Call {self.__name__}(...) and/or assign the result to a variable to use."
            )

        cached = self._ensure_cached()
        return cached.name if cached is not None else self.name

    def _ensure_cached(self) -> Table | None:
        if self._cached_table is None:
            kwargs = self.get_default_kwargs()
            if kwargs is not None:
                self._cached_table = self(**kwargs)
        return self._cached_table

    def __getattr__(self, name):
        cached = self._ensure_cached()
        if cached is None:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'. "
                f"Table requires arguments and cannot be auto-initialized."
            )
        return getattr(cached, name)

    def __repr__(self):
        cached = self._ensure_cached()
        return repr(cached) if cached else f"Table({self.name}) (uninitialized)"

    def _repr_html_(self):
        return self.__getattr__('_repr_html_')()

    def sql(self, query: str):
        return self.__getattr__('sql')(query)

    @property
    def columns(self):
        return self.__getattr__('columns')

    @property
    def graph(self):
        return self.__getattr__('graph')

    @property
    def df(self):
        return self.__getattr__('df')