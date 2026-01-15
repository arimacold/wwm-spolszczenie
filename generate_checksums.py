import hashlib, json, os

files = [
    "translate_words_map_en",
    "translate_words_map_en_diff"
]

checksums = {}

for f in files:
    with open(os.path.join("files", f), "rb") as file:
        checksums[f] = hashlib.sha256(file.read()).hexdigest()

with open("files/checksums.json", "w") as out:
    json.dump(checksums, out, indent=2)

print("Gotowe")
