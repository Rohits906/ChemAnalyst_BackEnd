import os

def check_exceptions():
    exceptions = [
        Exception("test"),
        OSError("test"),
        ValueError("test"),
        RuntimeError("test"),
    ]
    
    for e in exceptions:
        s = str(e)
        if "VSCODE" in s or "WINDIR" in s:
            print(f"FOUND LEAK IN {type(e).__name__}: {s[:100]}...")
        else:
            print(f"No leak in {type(e).__name__}")

if __name__ == "__main__":
    check_exceptions()
