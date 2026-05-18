import subprocess
import textwrap

SQLCL_CMD = [
    "sql",
    "-cloudconfig",
    "/home/opc/wallet/Wallet_HKT202602.zip",
    "HKTR1G4/Hk1_ySVtqYZp-Dayk_zl@hkt202602_high",
]

SQL = textwrap.dedent(
    """
    set heading off feedback off pagesize 0 verify off
    select table_name from user_tables order by table_name;
    exit;
    """
).strip() + "\n"


def main() -> None:
    try:
        result = subprocess.run(
            SQLCL_CMD,
            input=SQL,
            universal_newlines=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=30,
        )
        output = result.stdout.strip()
        print("Connected via SQLcl from Python")
        print(output)
    except subprocess.CalledProcessError as e:
        print("Database access failed")
        print(e.stdout)
        print(e.stderr)
        raise
    except subprocess.TimeoutExpired:
        print("Database access timed out")
        raise


if __name__ == "__main__":
    main()
