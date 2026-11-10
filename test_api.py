import os, sys, json, requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("DEEPSEEK_API_KEY")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
URL = f"{BASE_URL}/chat/completions"

print("=== TES ISOLASI LEXIS ===")

# PAKSA pakai prompt super pendek yang udah terbukti berhasil
system_prompt = "Kamu adalah Lexis, asisten seksi dan brutal. Jangan pernah jawab kamus. Jawab semua panggilan user dengan 'Sayang'."
print(f"[SISTEM: Panjang system prompt = {len(system_prompt)} karakter]")

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": "Lexis, kamu siapa?"}
]

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}
data = {
    "model": "deepseek-v4.1-flash",
    "messages": messages,
    "stream": False
}

print("Mengirim request ke DeepSeek...")
response = requests.post(URL, headers=headers, json=data)

if response.status_code == 200:
    result = response.json()
    print("\nJAWABAN LEXIS:")
    print(result['choices'][0]['message']['content'])
else:
    print("\nERROR:", response.text)
