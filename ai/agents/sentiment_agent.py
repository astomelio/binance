import os
import duckdb
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import json
import logging
from typing import List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def analyze_news_sentiment(db_path: str):
    """
    Reads un-analyzed news from the database, uses LangChain to extract sentiment,
    and saves the results to a new table.
    """
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.warning("OPENAI_API_KEY no encontrada. Generando sentimientos simulados (dummy) para que el pipeline funcione.")
        # We will not return, we will just generate random/dummy sentiments.
    
    conn = duckdb.connect(db_path)
    
    # Create sentiment table if it doesn't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS main.news_sentiment (
            uuid VARCHAR PRIMARY KEY,
            symbol VARCHAR,
            sentiment_score DOUBLE,
            sentiment_label VARCHAR,
            ai_summary VARCHAR,
            analyzed_at VARCHAR
        )
    """)
    
    # Fetch news from market_news that haven't been analyzed yet (not in news_sentiment)
    try:
        # Check if market_news exists (stock_market_ingest creates it)
        tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_name='market_news'").fetchall()
        if not tables:
            logger.info("market_news table not found (run stock_market_ingest first). news_sentiment will be empty.")
            conn.close()
            return
        query = """
            SELECT m.uuid, m.symbol, m.title, m.provider_publish_time
            FROM main.market_news m
            LEFT JOIN main.news_sentiment s ON m.uuid = s.uuid
            WHERE s.uuid IS NULL
            LIMIT 50
        """
        news_to_analyze = conn.execute(query).fetchdf().to_dict('records')
    except Exception as e:
        logger.error(f"Error fetching news: {e}")
        conn.close()
        return

    if not news_to_analyze:
        logger.info("No hay noticias nuevas para analizar.")
        conn.close()
        return

    if not api_key:
        chat = None
    else:
        chat = ChatOpenAI(temperature=0, openai_api_key=api_key, model="gpt-3.5-turbo")
    
    results = []
    from datetime import datetime
    import random
    
    for item in news_to_analyze:
        logger.info(f"Analizando: {item['symbol']} - {item['title']}")
        
        if not api_key:
            # Dummy logic
            score = random.uniform(-0.5, 0.5)
            label = "NEUTRAL"
            if score > 0.2: label = "POSITIVO"
            elif score < -0.2: label = "NEGATIVO"
            
            results.append({
                'uuid': item['uuid'],
                'symbol': item['symbol'],
                'sentiment_score': score,
                'sentiment_label': label,
                'ai_summary': "Análisis simulado por falta de API key.",
                'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            continue

        prompt = f"""
        Eres un analista financiero experto. Analiza el siguiente titular de noticias para la acción {item['symbol']} y determina su impacto en el precio de la acción a corto plazo.
        
        Titular: "{item['title']}"
        
        Responde estrictamente en el siguiente formato JSON y nada más:
        {{
            "score": <número entre -1.0 (muy negativo) y 1.0 (muy positivo)>,
            "label": "<POSITIVO, NEGATIVO, o NEUTRAL>",
            "summary": "<Resumen de 1 oración del impacto>"
        }}
        """
        
        try:
            response = chat.invoke([HumanMessage(content=prompt)])
            # Parse JSON
            content = response.content.replace("```json", "").replace("```", "").strip()
            data = json.loads(content)
            
            results.append({
                'uuid': item['uuid'],
                'symbol': item['symbol'],
                'sentiment_score': float(data['score']),
                'sentiment_label': data['label'],
                'ai_summary': data['summary'],
                'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
        except Exception as e:
            logger.error(f"Error analyzing item {item['uuid']}: {e}")
            
    # Save results to duckdb
    if results:
        import pandas as pd
        df = pd.DataFrame(results)
        conn.register('temp_results', df)
        conn.execute("""
            INSERT INTO main.news_sentiment
            SELECT * FROM temp_results
        """)
        logger.info(f"Análisis completado. {len(results)} noticias analizadas e insertadas.")
        
    conn.close()

if __name__ == "__main__":
    db_path = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    analyze_news_sentiment(db_path)
