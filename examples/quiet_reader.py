"""A deliberately faulty file reader, used in the README example."""
import sys

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        print(len(f.read().split()), "words")
except FileNotFoundError:
    sys.exit(1)  # fault: exits non-zero but says nothing
