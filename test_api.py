import requests, json

API_KEY = 'AIzaSyBQR_5j0iWY2ylX9zFI7kl9o2rUeTZEyGo'
URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'

prompt = 'Analyze this resume and return ONLY valid JSON with keys: score (int), summary (str), skills_detected (list). Resume: John Doe, Python developer, 3 years experience with Django and Flask.'

resp = requests.post(
    URL,
    params={'key': API_KEY},
    json={
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.3,
            'maxOutputTokens': 4096,
            'responseMimeType': 'application/json',
            'thinkingConfig': {'thinkingBudget': 0},
        },
    },
    timeout=30
)
print('Status:', resp.status_code)
data = resp.json()
if resp.status_code != 200:
    print('ERROR:', json.dumps(data, indent=2))
else:
    parts = data['candidates'][0]['content']['parts']
    raw = ''.join(p.get('text', '') for p in parts)
    print('Raw:', raw[:400])
    start = raw.find('{')
    end = raw.rfind('}')
    if start != -1 and end != -1:
        parsed = json.loads(raw[start:end+1])
        print('PARSED OK:', parsed)
    else:
        print('No JSON found')
