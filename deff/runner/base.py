from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Result(ABC):
    @abstractmethod
    def df(self) -> pd.DataFrame: ...

    @property
    @abstractmethod
    def columns(self) -> list[str]: ...

    @property
    @abstractmethod
    def types(self) -> list[str]: ...

    @abstractmethod
    def fetchall(self) -> list[tuple]: ...

    @abstractmethod
    def fetchmany(self, n: int) -> list[tuple]: ...

    @abstractmethod
    def fetchone(self) -> tuple | None: ...

    @abstractmethod
    def __iter__(self): ...

    @abstractmethod
    def __len__(self) -> int: ...
