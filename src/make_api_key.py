"""Usage:
  python src/make_api_key.py school-a https://www.school-a.edu.my      -> browser key (chat box on a website)
  python src/make_api_key.py parenting-app                             -> server key (called from their backend)
Prints a new random key and the lines to add to Render > Environment."""
import re, secrets, sys

name = re.sub(r"[^a-z0-9-]", "", (sys.argv[1] if len(sys.argv) > 1 else "partner").lower()) or "partner"
sites = [u.rstrip("/") for u in sys.argv[2:]]
key = "mc_" + secrets.token_urlsafe(32)
print(f"Key for '{name}' (shown only now, give it to the partner):\n  {key}\n")
print("1) Append to API_KEYS (comma-separated):")
print(f"  {name}:{key}")
if sites:
    print("2) Append to API_ORIGINS (semicolon-separated). This makes it a BROWSER key, valid only on these sites:")
    print(f"  {name}={'|'.join(sites)}")
else:
    print("2) No API_ORIGINS entry = SERVER key: it is refused if a browser sends it. Never put it in website JavaScript.")
print(f"3) Optional: without a file the key gets MelodyCare's own visitor assistant. To make it a partner assistant with its own details, create data/tenants/{name}.txt (see data/tenants/_example.txt)")
