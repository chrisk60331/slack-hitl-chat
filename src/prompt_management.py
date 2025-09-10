
import os
os.environ["PEZZO_API_KEY"] = "pez_9dea607c4a3882ab9f2c43734c62b9a3"
os.environ["PEZZO_PROJECT_ID"] = "cmfd1jusd00049knd72pyi34a"
os.environ["PEZZO_ENVIRONMENT"] = "Production"
os.environ["PEZZO_SERVER_URL"] = "http://localhost:3000"

from pezzo.client import pezzo
prompt = pezzo.get_prompt("Agent")
print(prompt.content.get("prompt"))
