import os
import duckdb
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def track_x_accounts_with_grok(db_path: str):
    """
    Uses the xAI (Grok) API to track specific X accounts, analyze their recent 
    sentiment regarding markets, and store the result.
    """
    xai_api_key = os.getenv('XAI_API_KEY')
    if not xai_api_key:
        logger.warning("XAI_API_KEY no encontrada. Generando sentimientos simulados (dummy) para el pipeline.")
    
    conn = duckdb.connect(db_path)
    
    # Create X sentiment table if it doesn't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS main.x_account_sentiment (
            account_handle VARCHAR,
            sentiment_score DOUBLE, -- -1.0 to 1.0
            sentiment_label VARCHAR,
            grok_summary VARCHAR,
            analyzed_at VARCHAR
        )
    """)
    
    # List of influential accounts to track
    accounts_to_track = [
        "@elonmusk", 
        "@VitalikButerin", 
        "@tier10k", 
        "@unusual_whales",
        "@cz_binance"
    ]
    
    # Initialize Grok via LangChain (using xAI base URL)
    if xai_api_key:
        chat = ChatOpenAI(
            temperature=0, 
            openai_api_key=xai_api_key, 
            openai_api_base="https://api.x.ai/v1",
            model="grok-beta" # or grok-2-latest
        )
    else:
        chat = None
        
    results = []
    import random
    
    for account in accounts_to_track:
        logger.info(f"Analizando actividad reciente de: {account} con Grok")
        
        if not chat:
            # Dummy logic for testing when API key is missing
            score = random.uniform(-0.8, 0.8)
            label = "NEUTRAL"
            if score > 0.3: label = "POSITIVO"
            elif score < -0.3: label = "NEGATIVO"
            
            results.append({
                'account_handle': account,
                'sentiment_score': score,
                'sentiment_label': label,
                'grok_summary': "Análisis simulado por falta de XAI_API_KEY.",
                'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            continue

        prompt = f"""
        Eres un analista financiero cuantitativo. Revisa las publicaciones más recientes en X (Twitter) de la cuenta {account} 
        y determina si su tono general actual respecto a los mercados financieros (cripto o acciones) es alcista (positivo) o bajista (negativo).
        
        Responde estrictamente en el siguiente formato JSON y nada más:
        {{
            "score": <número entre -1.0 (muy negativo) y 1.0 (muy positivo)>,
            "label": "<POSITIVO, NEGATIVO, o NEUTRAL>",
            "summary": "<Resumen de 1 oración de su postura actual>"
        }}
        """
        
        try:
            response = chat.invoke([HumanMessage(content=prompt)])
            content = response.content.replace("```json", "").replace("```", "").strip()
            data = json.loads(content)
            
            results.append({
                'account_handle': account,
                'sentiment_score': float(data.get('score', 0.0)),
                'sentiment_label': data.get('label', 'NEUTRAL'),
                'grok_summary': data.get('summary', ''),
                'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
        except Exception as e:
            logger.error(f"Error analyzing account {account}: {e}")
            
    # Save results to duckdb
    if results:
        import pandas as pd
        df = pd.DataFrame(results)
        conn.register('temp_x_results', df)
        conn.execute("""
            INSERT INTO main.x_account_sentiment
            SELECT * FROM temp_x_results
        """)
        logger.info(f"Análisis de X completado. {len(results)} cuentas analizadas.")
        
    conn.close()

if __name__ == "__main__":
    db_path = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    track_x_accounts_with_grok(db_path)
