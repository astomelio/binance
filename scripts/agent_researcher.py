import os
import sys
import time
import json
import random
import logging
from pathlib import Path
from datetime import datetime

# Añadir el root del proyecto al PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_platform.storage.duckdb_facade import DuckDBFacade
from ai.explorer.optimizer import run_optimization
from ai.inference.champion_loader import enrich_rows_with_champion
from ai.allocation.checks import warn_alpha_score_if_low
from ai.explorer.data_filters import get_symbol_set

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("researcher_agent.log", encoding='utf-8')
    ]
)

# Configuración del Agente
TARGET_SHARPE = 2.0
TARGET_RETURN_PERCENT = 0.50 # 50%
MAX_STAGNATION_BATCHES = 3   # Cuántos lotes seguidos sin mejora antes de cambiar de enfoque
TRIALS_PER_BATCH = 50        # Combinaciones a probar por lote
CANDIDATES_FILE = "artifacts/quant_model/discovered_candidates.json"

class ResearcherAgent:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.best_overall_sharpe = -999.0
        self.batches_without_improvement = 0
        self.total_candidates_found = 0
        
        # Diferentes "modos de búsqueda" que el agente puede alternar
        self.search_spaces = {
            "mr_deep_dive": {
                "desc": "Profundizando en parámetros de Mean Reversion (oversold/overbought/window)",
                "strategy_ids": ["mean_reversion"],
                "horizons": ["4h", "12h", "24h"],
                "symbol_sets": ["top_10", "top_20"],
                "param_overrides": {
                    "window": [6, 12, 24, 48, 72],
                    "oversold": [15, 20, 25, 30],
                    "overbought": [70, 75, 80, 85]
                }
            },
            "alpha_tuning": {
                "desc": "Afinando umbrales de predicción del modelo LightGBM (Alpha Score)",
                "strategy_ids": ["alpha_score"],
                "horizons": ["1h", "4h", "12h"],
                "symbol_sets": ["top_10", "top_50"],
                "param_overrides": {
                    "threshold": [0.51, 0.53, 0.55, 0.58, 0.60],
                    "max_assets": [1, 2, 3, 5]
                }
            },
            "horizon_shift": {
                "desc": "Buscando oportunidades en temporalidades extremas (muy corto o muy largo plazo)",
                "strategy_ids": ["alpha_score", "mean_reversion"],
                "horizons": ["1h", "2h", "48h", "72h"],
                "symbol_sets": ["top_20"],
                "param_overrides": None
            },
            "asset_exploration": {
                "desc": "Explorando el comportamiento en diferentes universos de monedas",
                "strategy_ids": ["alpha_score", "mean_reversion"],
                "horizons": ["12h", "24h"],
                "symbol_sets": ["top_5", "top_10", "top_20", "top_50", "vol_trend"],
                "param_overrides": None
            }
        }
        
        self.current_space_name = random.choice(list(self.search_spaces.keys()))
        
        # Asegurar que el directorio de candidatos existe
        os.makedirs(os.path.dirname(CANDIDATES_FILE), exist_ok=True)
        if not os.path.exists(CANDIDATES_FILE):
            with open(CANDIDATES_FILE, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def pivot_strategy(self):
        """Cambia el espacio de búsqueda cuando está estancado."""
        available_spaces = [k for k in self.search_spaces.keys() if k != self.current_space_name]
        self.current_space_name = random.choice(available_spaces)
        self.batches_without_improvement = 0
        logging.warning(f"🔄 Agente estancado. Pivotando a nuevo enfoque: {self.current_space_name} - {self.search_spaces[self.current_space_name]['desc']}")

    def save_candidate(self, result):
        """Guarda un modelo que superó los umbrales en el archivo de candidatos."""
        with open(CANDIDATES_FILE, 'r', encoding='utf-8') as f:
            candidates = json.load(f)
            
        candidate_data = {
            "discovered_at": datetime.utcnow().isoformat(),
            "strategy": result.strategy_id,
            "params": result.params,
            "horizon": result.horizon,
            "symbol_set": result.meta.get("symbol_set", "unknown"),
            "metrics": result.metrics
        }
        
        # Evitar duplicados exactos
        is_duplicate = any(
            c["strategy"] == candidate_data["strategy"] and 
            c["params"] == candidate_data["params"] and 
            c["horizon"] == candidate_data["horizon"] and
            c["symbol_set"] == candidate_data["symbol_set"]
            for c in candidates
        )
        
        if not is_duplicate:
            candidates.append(candidate_data)
            with open(CANDIDATES_FILE, 'w', encoding='utf-8') as f:
                json.dump(candidates, f, indent=2)
            self.total_candidates_found += 1
            logging.info(f"🏆 ¡NUEVO CANDIDATO GUARDADO! Sharpe: {result.metrics['sharpe_ratio']:.2f}, Retorno: {result.metrics['total_return']*100:.1f}%. Total candidatos: {self.total_candidates_found}")

    def run_forever(self):
        logging.info("🧠 Agente Investigador Iniciado. Trabajando de forma autónoma...")
        logging.info(f"🎯 Objetivos: Sharpe > {TARGET_SHARPE}, Retorno > {TARGET_RETURN_PERCENT*100}%")
        
        batch_count = 0
        
        while True:
            batch_count += 1
            space = self.search_spaces[self.current_space_name]
            
            logging.info(f"\n--- Lote #{batch_count} | Enfoque: {self.current_space_name} ---")
            
            try:
                # Ejecutar el optimizador con el espacio de búsqueda actual
                results = run_optimization(
                    rows=self.rows,
                    strategy_ids=space["strategy_ids"],
                    horizons=space["horizons"],
                    symbol_sets=space["symbol_sets"],
                    session_hours=None, # Todo el día por ahora
                    max_total_trials=TRIALS_PER_BATCH,
                    param_overrides=space.get("param_overrides"),
                    random_seed=random.randint(0, 10000) # Cambiar semilla para explorar nuevas combinaciones
                )
                
                if not results:
                    logging.warning("No se generaron resultados válidos en este lote. Pivotando...")
                    self.pivot_strategy()
                    continue
                
                # Encontrar el mejor del lote
                best_in_batch = max(results, key=lambda x: x.metrics.get('sharpe_ratio', -999))
                batch_sharpe = best_in_batch.metrics.get('sharpe_ratio', -999)
                batch_return = best_in_batch.metrics.get('total_return', -999)
                
                logging.info(f"Mejor del lote: {best_in_batch.strategy_id} | Sharpe: {batch_sharpe:.2f} | Retorno: {batch_return*100:.1f}%")
                
                # Evaluar progreso
                if batch_sharpe > self.best_overall_sharpe + 0.05: # Considerar mejora si supera por 0.05
                    logging.info(f"📈 Progreso detectado! Nuevo mejor Sharpe global: {batch_sharpe:.2f} (antes {self.best_overall_sharpe:.2f})")
                    self.best_overall_sharpe = batch_sharpe
                    self.batches_without_improvement = 0
                else:
                    self.batches_without_improvement += 1
                    logging.info(f"⏳ Sin mejora global significativa. Lotes estancado: {self.batches_without_improvement}/{MAX_STAGNATION_BATCHES}")
                
                # Evaluar si merece ser guardado como candidato élite
                if batch_sharpe >= TARGET_SHARPE and batch_return >= TARGET_RETURN_PERCENT:
                    self.save_candidate(best_in_batch)
                    
                # Si estamos estancados, cambiar de estrategia
                if self.batches_without_improvement >= MAX_STAGNATION_BATCHES:
                    self.pivot_strategy()
                    
            except Exception as e:
                logging.error(f"Error durante el lote de optimización: {e}")
                time.sleep(5) # Esperar antes de reintentar
                
            # Pequeña pausa para no quemar la CPU al 100% todo el tiempo y simular "pensamiento"
            time.sleep(2)

def main():
    logging.info("Iniciando carga de datos para el Agente Investigador...")
    db = DuckDBFacade()
    
    # Cargar datos (últimos 90 días suele ser suficiente para búsqueda ágil, pero puedes poner 180)
    query = """
    SELECT * FROM main.decision_features 
    WHERE timestamp >= current_date - interval 90 day
    ORDER BY timestamp ASC
    """
    df = db.query(query)
    
    if df.empty:
        logging.error("No se encontraron datos en decision_features. Asegúrate de correr el pipeline de datos primero.")
        return
        
    rows = df.to_dict(orient='records')
    logging.info(f"Datos cargados: {len(rows)} filas.")
    
    # Enriquecer con el modelo champion para que 'alpha_score' funcione
    logging.info("Enriqueciendo datos con el modelo de ML (Champion)...")
    try:
        rows = enrich_rows_with_champion(rows)
        warn_alpha_score_if_low(rows)
    except Exception as e:
        logging.error(f"Fallo al cargar el modelo champion. Las estrategias de alpha_score podrían no funcionar. Error: {e}")
    
    # Iniciar el agente
    agent = ResearcherAgent(rows)
    try:
        agent.run_forever()
    except KeyboardInterrupt:
        logging.info("Agente Investigador detenido manualmente.")
        logging.info(f"Resumen: {agent.total_candidates_found} candidatos élite descubiertos.")

if __name__ == "__main__":
    main()
