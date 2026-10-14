import sys
from unittest import mock
from alembic.config import main


def run():
    with mock.patch("google.auth.default", return_value=(mock.Mock(), "dummy-project")):
        main(sys.argv[1:])


if __name__ == "__main__":
    run()
