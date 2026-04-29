from __future__ import annotations

import contextvars
import inspect

from .base import REGISTRY, SESSION, clean_sql, extract_table_names
from .table import Table, sql

_composition_deps: contextvars.ContextVar[tuple[list, ...]] = contextvars.ContextVar(
    "composition_deps", default=()
)


class tbl:
    def __init__(self, func):
        self._func = func
        self.name = _qualified_name(func)
        self._cached_table: Table | None = None
        self.__wrapped__ = func
        self.__name__ = func.__name__
        self.__doc__ = func.__doc__

        stack = _composition_deps.get()
        self.is_local = bool(stack)

        if not self.is_local:
            REGISTRY[self.name] = self

    def __call__(self, *args, **kwargs):
        sig = inspect.signature(self._func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        all_args = dict(bound.arguments)

        local_deps: list[Table] = []
        token = _composition_deps.set(_composition_deps.get() + (local_deps,))
        try:
            sql = self._func(*args, **kwargs)
        finally:
            _composition_deps.reset(token)

        referenced = extract_table_names(clean_sql(sql))

        for val in all_args.values():
            if isinstance(val, Table):
                local_deps.append(val)

        local_deps = [d for d in local_deps if d.name in referenced]

        ctes = [d.spec for d in local_deps if d.is_cte]
        deps = [d.spec for d in local_deps if not d.is_cte]

        table = Table(
            sql=sql, func_name=self.name, args=all_args,
            deps=deps, ctes=ctes, is_cte=self.is_local,
        )

        if not self.is_local:
            SESSION["last_args"][self.name] = all_args

        stack = _composition_deps.get()
        if stack:
            stack[-1].append(table)

        return table

    def __str__(self):
        if self.is_local:
            if self._cached_table is None:
                self._cached_table = self()
            stack = _composition_deps.get()
            if stack and not any(d is self._cached_table for d in stack[-1]):
                stack[-1].append(self._cached_table)
            return self._cached_table.name
        return self.name

    def __repr__(self):
        return f"tbl({self.name})"

    def get_default_kwargs(self) -> dict | None:
        sig = inspect.signature(self._func)
        try:
            bound = sig.bind()
            bound.apply_defaults()
            return dict(bound.arguments)
        except TypeError:
            return None


def _qualified_name(func) -> str:
    module = func.__module__.rsplit(".", 1)[-1]
    if module == "__main__":
        return func.__name__
    return f"{module}__{func.__name__}"