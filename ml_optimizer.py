import os
import json
from datetime import datetime
from collections import defaultdict
from tinydb import TinyDB

class TradePredictor:
    def __init__(self):
        self.prior_win = 0.5
        self.prior_loss = 0.5
        # Conditional probability tables: feature -> value -> class -> probability
        self.cond_probs = defaultdict(lambda: defaultdict(lambda: {"WIN": 0.5, "LOSS": 0.5}))
        self.feature_cardinality = {}
        self.is_trained = False

    def _get_session(self, hour):
        if 0 <= hour < 8:
            return "Asian"
        elif 8 <= hour < 16:
            return "London"
        else:
            return "NewYork"

    def _extract_features(self, trade):
        # Extract features from a trade dictionary
        pattern = trade.get("pattern", "Unknown")
        direction = trade.get("type", "Unknown")
        candle_pattern = trade.get("candle_pattern", "Unknown")
        
        # Parse time to extract session and day of week
        time_str = trade.get("time", "")
        session = "London"
        day_of_week = "Monday"
        if time_str:
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                session = self._get_session(dt.hour)
                day_of_week = dt.strftime("%A")
            except Exception:
                pass
                
        return {
            "pattern": pattern,
            "direction": direction,
            "candle_pattern": candle_pattern,
            "session": session,
            "day_of_week": day_of_week
        }

    def train(self, trades):
        if not trades:
            self.is_trained = False
            return
            
        win_trades = [t for t in trades if t.get("result") == "WIN"]
        loss_trades = [t for t in trades if t.get("result") == "LOSS"]
        
        total_win = len(win_trades)
        total_loss = len(loss_trades)
        total_all = total_win + total_loss
        
        if total_all == 0:
            self.is_trained = False
            return
            
        # Prior probabilities
        self.prior_win = (total_win + 1) / (total_all + 2)
        self.prior_loss = (total_loss + 1) / (total_all + 2)
        
        # Calculate feature counts
        # counts[feature][value][class] = count
        counts = defaultdict(lambda: defaultdict(lambda: {"WIN": 0, "LOSS": 0}))
        unique_values = defaultdict(set)
        
        for t in trades:
            result = t.get("result")
            if result not in ("WIN", "LOSS"):
                continue
            feats = self._extract_features(t)
            for f, val in feats.items():
                counts[f][val][result] += 1
                unique_values[f].add(val)
                
        # Calculate conditional probabilities with Laplace smoothing
        self.cond_probs = defaultdict(lambda: defaultdict(lambda: {"WIN": 0.5, "LOSS": 0.5}))
        for f, values in counts.items():
            cardinality = len(unique_values[f])
            self.feature_cardinality[f] = cardinality
            for val, class_counts in values.items():
                prob_win = (class_counts["WIN"] + 1) / (total_win + cardinality)
                prob_loss = (class_counts["LOSS"] + 1) / (total_loss + cardinality)
                self.cond_probs[f][val] = {"WIN": prob_win, "LOSS": prob_loss}
                
        self.is_trained = True
        print(f"ML Model trained successfully on {total_all} trades. (Wins: {total_win}, Losses: {total_loss})")

    def predict_win_probability(self, new_trade_setup):
        """
        Predict probability of WIN for a new setup.
        new_trade_setup keys: 'pattern', 'direction' (BUY/SELL), 'candle_pattern', 'time' (optional, defaults to now)
        """
        if not self.is_trained:
            return 0.78  # Return default confidence if not trained
            
        feats = self._extract_features(new_trade_setup)
        
        # Multiply likelihoods * prior
        likelihood_win = self.prior_win
        likelihood_loss = self.prior_loss
        
        for f, val in feats.items():
            # If feature value is unseen during training, use Laplace smoothing baseline
            cardinality = self.feature_cardinality.get(f, 3)
            
            if val in self.cond_probs[f]:
                p_win = self.cond_probs[f][val]["WIN"]
                p_loss = self.cond_probs[f][val]["LOSS"]
            else:
                p_win = 1.0 / (cardinality + 1)
                p_loss = 1.0 / (cardinality + 1)
                
            likelihood_win *= p_win
            likelihood_loss *= p_loss
            
        # Normalize to get probability
        total_likelihood = likelihood_win + likelihood_loss
        if total_likelihood == 0:
            return 0.5
            
        prob_win = likelihood_win / total_likelihood
        return prob_win

# Initialize global predictor
ai_predictor = TradePredictor()

def train_predictor_from_db():
    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.json")
        if os.path.exists(db_path):
            db = TinyDB(db_path)
            trades_table = db.table("trades")
            trades = trades_table.all()
            ai_predictor.train(trades)
    except Exception as e:
        print(f"Error training ML model: {e}")
