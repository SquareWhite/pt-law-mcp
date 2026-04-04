from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator

from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver, Session
from neo4j.exceptions import ServiceUnavailable, AuthError

load_dotenv()

logger = logging.getLogger(__name__)

_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "legalGraphDev")
        try:
            _driver = GraphDatabase.driver(uri, auth=(user, password))
            _driver.verify_connectivity()
            logger.debug("Connected to Neo4j at %s", uri)
        except ServiceUnavailable as exc:
            raise RuntimeError(
                f"Cannot reach Neo4j at {uri}. "
                "Is the database running? Check NEO4J_URI."
            ) from exc
        except AuthError as exc:
            raise RuntimeError(
                "Neo4j authentication failed. Check NEO4J_USER and NEO4J_PASSWORD."
            ) from exc
    return _driver


@contextmanager
def get_session() -> Generator[Session, None, None]:
    try:
        driver = get_driver()
        with driver.session() as session:
            yield session
    except ServiceUnavailable as exc:
        raise RuntimeError(
            "Lost connection to Neo4j during operation."
        ) from exc


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
