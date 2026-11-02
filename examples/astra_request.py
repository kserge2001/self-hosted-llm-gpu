"""Call the Astra gateway from an application; use your hostname and key."""
from getpass import getpass
from openai import OpenAI

client = OpenAI(
    base_url="https://YOUR_ASTRA_HOST/v1",
    api_key=getpass("Astra application key: "),
)

response = client.chat.completions.create(
    model="astra",
    messages=[{"role": "user", "content": "Explain a Kubernetes Service in two sentences."}],
    max_tokens=160,
)

print(response.choices[0].message.content)
