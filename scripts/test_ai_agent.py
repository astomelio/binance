import requests

def talk_to_agent(query):
    url = "http://localhost:8000/agent/chat"
    try:
        response = requests.post(url, json={"query": query})
        return response.json()
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print("--- CONSULTANDO AL AGENTE ---")
    # Ejemplo de consulta
    q = "¿Cual es el mejor modelo que encontraste y cual es su retorno esperado?"
    res = talk_to_agent(q)
    print(f"Respuesta del Sistema: {res}")
