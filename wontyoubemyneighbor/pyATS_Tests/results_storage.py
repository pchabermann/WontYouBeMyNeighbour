"""
PyATS Test Results Storage
Provides persistent storage for test results using SQLite
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Single test result"""
    test_id: str
    test_name: str
    suite_name: str
    status: str  # passed, failed, skipped, error
    description: str
    failure_reason: Optional[str] = None
    duration_ms: float = 0.0
    timestamp: str = ""
    agent_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class TestRunSummary:
    """Summary of a test run"""
    run_id: int
    agent_id: str
    timestamp: str
    total_suites: int
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    pass_rate: float
    duration_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


class TestResultsStorage:
    """
    Persistent storage for pyATS test results

    Stores test results in SQLite database in ~/.asi/test_results.db
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize storage

        Args:
            db_path: Path to SQLite database. If None, uses ~/.asi/test_results.db
        """
        if db_path is None:
            asi_dir = Path.home() / ".asi"
            asi_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(asi_dir / "test_results.db")

        self.db_path = db_path
        self._init_database()
        logger.info(f"Initialized test results storage at {self.db_path}")

    def _init_database(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Test runs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS test_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                total_suites INTEGER,
                total_tests INTEGER,
                passed INTEGER,
                failed INTEGER,
                skipped INTEGER,
                errors INTEGER,
                pass_rate REAL,
                duration_seconds REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Test results table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS test_results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                test_id TEXT NOT NULL,
                test_name TEXT NOT NULL,
                suite_name TEXT NOT NULL,
                status TEXT NOT NULL,
                description TEXT,
                failure_reason TEXT,
                duration_ms REAL,
                timestamp TEXT,
                agent_id TEXT,
                FOREIGN KEY (run_id) REFERENCES test_runs(run_id)
            )
        """)

        # Indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_id ON test_runs(agent_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON test_runs(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_run_id ON test_results(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_result_agent ON test_results(agent_id)")

        conn.commit()
        conn.close()

    def store_test_run(self, agent_id: str, results: List[Dict[str, Any]],
                      summary: Dict[str, Any]) -> int:
        """
        Store a complete test run with all results

        Args:
            agent_id: Agent identifier
            results: List of test result dictionaries
            summary: Test run summary dictionary

        Returns:
            run_id of the stored test run
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            timestamp = datetime.now().isoformat()

            # Insert test run summary
            cursor.execute("""
                INSERT INTO test_runs
                (agent_id, timestamp, total_suites, total_tests, passed, failed,
                 skipped, errors, pass_rate, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                agent_id,
                timestamp,
                summary.get('total_suites', 0),
                summary.get('total_tests', 0),
                summary.get('passed', 0),
                summary.get('failed', 0),
                summary.get('skipped', 0),
                summary.get('errors', 0),
                summary.get('pass_rate', 0.0),
                summary.get('duration_seconds', 0.0)
            ))

            run_id = cursor.lastrowid

            # Insert individual test results
            for result in results:
                cursor.execute("""
                    INSERT INTO test_results
                    (run_id, test_id, test_name, suite_name, status, description,
                     failure_reason, duration_ms, timestamp, agent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    result.get('test_id', ''),
                    result.get('test_name', ''),
                    result.get('suite_name', ''),
                    result.get('status', 'unknown'),
                    result.get('description', ''),
                    result.get('failure_reason'),
                    result.get('duration', 0.0),
                    result.get('timestamp', timestamp),
                    agent_id
                ))

            conn.commit()
            logger.info(f"Stored test run {run_id} for agent {agent_id} with {len(results)} results")
            return run_id

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to store test run: {e}")
            raise
        finally:
            conn.close()

    def get_latest_results(self, agent_id: str, limit: int = 50) -> Dict[str, Any]:
        """
        Get latest test results for an agent

        Args:
            agent_id: Agent identifier
            limit: Maximum number of test results to return

        Returns:
            Dictionary with results, timestamp, and summary
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get latest test run
            cursor.execute("""
                SELECT run_id, timestamp, total_suites, total_tests, passed, failed,
                       skipped, errors, pass_rate, duration_seconds
                FROM test_runs
                WHERE agent_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (agent_id,))

            run_row = cursor.fetchone()

            if not run_row:
                return {
                    "results": [],
                    "timestamp": None,
                    "summary": {}
                }

            run_id, timestamp, total_suites, total_tests, passed, failed, skipped, errors, pass_rate, duration = run_row

            # Get test results for this run
            cursor.execute("""
                SELECT test_id, test_name, suite_name, status, description,
                       failure_reason, duration_ms, timestamp
                FROM test_results
                WHERE run_id = ?
                ORDER BY result_id DESC
                LIMIT ?
            """, (run_id, limit))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "test_id": row[0],
                    "test_name": row[1],
                    "suite_name": row[2],
                    "status": row[3],
                    "description": row[4],
                    "failure_reason": row[5],
                    "duration": row[6],
                    "timestamp": row[7]
                })

            summary = {
                "total_suites": total_suites,
                "total_tests": total_tests,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "errors": errors,
                "pass_rate": pass_rate,
                "duration_seconds": duration
            }

            return {
                "results": results,
                "timestamp": timestamp,
                "summary": summary,
                "run_id": run_id
            }

        finally:
            conn.close()

    def get_test_history(self, agent_id: str, limit: int = 10) -> List[TestRunSummary]:
        """
        Get test run history for an agent

        Args:
            agent_id: Agent identifier
            limit: Maximum number of runs to return

        Returns:
            List of TestRunSummary objects
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT run_id, agent_id, timestamp, total_suites, total_tests,
                       passed, failed, skipped, errors, pass_rate, duration_seconds
                FROM test_runs
                WHERE agent_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (agent_id, limit))

            history = []
            for row in cursor.fetchall():
                history.append(TestRunSummary(
                    run_id=row[0],
                    agent_id=row[1],
                    timestamp=row[2],
                    total_suites=row[3],
                    total_tests=row[4],
                    passed=row[5],
                    failed=row[6],
                    skipped=row[7],
                    errors=row[8],
                    pass_rate=row[9],
                    duration_seconds=row[10]
                ))

            return history

        finally:
            conn.close()

    def cleanup_old_results(self, agent_id: str, keep_last: int = 100):
        """
        Clean up old test results, keeping only the most recent N runs

        Args:
            agent_id: Agent identifier
            keep_last: Number of most recent runs to keep
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get run_ids to delete
            cursor.execute("""
                SELECT run_id FROM test_runs
                WHERE agent_id = ?
                ORDER BY timestamp DESC
                LIMIT -1 OFFSET ?
            """, (agent_id, keep_last))

            old_run_ids = [row[0] for row in cursor.fetchall()]

            if old_run_ids:
                # Delete test results
                placeholders = ','.join('?' * len(old_run_ids))
                cursor.execute(f"""
                    DELETE FROM test_results
                    WHERE run_id IN ({placeholders})
                """, old_run_ids)

                # Delete test runs
                cursor.execute(f"""
                    DELETE FROM test_runs
                    WHERE run_id IN ({placeholders})
                """, old_run_ids)

                conn.commit()
                logger.info(f"Cleaned up {len(old_run_ids)} old test runs for agent {agent_id}")

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to cleanup old results: {e}")
        finally:
            conn.close()


# Global storage instance
_storage: Optional[TestResultsStorage] = None


def get_storage() -> TestResultsStorage:
    """Get or create global storage instance"""
    global _storage
    if _storage is None:
        _storage = TestResultsStorage()
    return _storage
