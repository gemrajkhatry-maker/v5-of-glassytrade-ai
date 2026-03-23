import sys
import pytest

class Tracer:
    def pytest_collection_finish(self, session):
        try:
            import shared
            print("\n---- DEBUG SHARED: ----")
            print("File:", getattr(shared, '__file__', 'unknown'))
            print("Type:", type(shared))
            print("Path:", getattr(shared, '__path__', 'unknown'))
            print("-----------------------\n")
        except Exception as e:
            print("\n---- DEBUG SHARED ERROR: ----")
            print(e)
            print("-----------------------\n")
            
        print("\nSYS PATH:")
        for p in sys.path:
            print(p)
        print("\n")

pytest.main(["tests/unit/test_fabio_alignment.py", "-v"], plugins=[Tracer()])
