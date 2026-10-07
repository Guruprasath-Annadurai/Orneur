"""PROTOTYPE_ONLY: lenient JSON implementations disagree (used only to justify a deterministic transfer encoding)."""
import json

print("py NaN:", json.loads('{"n":NaN}'))
print("py duplicate key:", json.loads('{"a":1,"a":2}'))
print("py big exponent:", json.loads('{"b":1e999}'))
