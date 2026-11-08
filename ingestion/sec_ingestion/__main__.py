import argparse
from .config import Settings
from .store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["bootstrap", "healthcheck"])
    parser.add_argument("--env-file")
    args = parser.parse_args()
    if args.command == "healthcheck":
        from urllib.request import urlopen
        with urlopen("http://127.0.0.1:8080/healthz", timeout=3) as response:
            if response.status != 200:
                raise SystemExit(1)
        return
    try:
        settings = Settings.load(args.env_file)
        store = Store.connect(settings)
        store.bootstrap()
        print("SECIngestion collections and indexes are ready. No legacy database was modified.")
    except Exception:
        raise SystemExit("Bootstrap failed. Check the SECIngestion URI, database permission, and network access; credentials were not printed.") from None


if __name__ == "__main__":
    main()
