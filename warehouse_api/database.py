import oracledb


class SqlclDatabase(object):
    """Run SQL against Oracle through a python-oracledb connection pool."""

    def __init__(self, settings):
        self.settings = settings
        self.pool = None

    def open(self):
        if self.pool is None:
            self.pool = oracledb.create_pool(
                user=self.settings.oracle_user,
                password=self.settings.oracle_password,
                dsn=self.settings.oracle_dsn,
                config_dir=self.settings.oracle_config_dir,
                wallet_location=self.settings.oracle_wallet_dir,
                min=self.settings.oracle_pool_min,
                max=self.settings.oracle_pool_max,
                increment=1,
            )
        return self.pool

    def close(self):
        if self.pool is not None:
            self.pool.close()
            self.pool = None
        return None

    def fetch_all(self, sql):
        statement = self._normalize_sql(sql)
        with self._acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(statement)
                if cur.description is None:
                    return []
                columns = [column[0].lower() for column in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

    def fetch_one(self, sql):
        rows = self.fetch_all(sql)
        if rows:
            return rows[0]
        return None

    def execute(self, sql):
        self.execute_script([sql])

    def execute_script(self, statements):
        with self._acquire() as conn:
            try:
                with conn.cursor() as cur:
                    for statement in statements:
                        cleaned = self._normalize_sql(statement)
                        if not cleaned:
                            continue
                        upper_statement = cleaned.upper()
                        if upper_statement == "COMMIT":
                            conn.commit()
                            continue
                        if upper_statement == "ROLLBACK":
                            conn.rollback()
                            continue
                        cur.execute(cleaned)
            except Exception:
                conn.rollback()
                raise

    def _acquire(self):
        if self.pool is None:
            self.open()
        return self.pool.acquire()

    def _normalize_sql(self, sql):
        cleaned = sql.strip()
        while cleaned.endswith(";"):
            cleaned = cleaned[:-1].rstrip()
        return cleaned


def sql_literal(value):
    """Escape a string for use as a SQL string literal."""
    return "'" + value.replace("'", "''") + "'"
