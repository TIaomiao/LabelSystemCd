
import re
import json

class ReportParser:
    def __init__(self):
        # Define regex patterns for metrics
        # (?i) case-insensitive
        # .*? non-greedy match for label text (e.g. "LVEF (Ejection Fraction)")
        # [:：] match both English and Chinese colons
        # \s* allow whitespace
        # (\d+\.?\d*) capture the number (integer or float)
        self.patterns = {
            'LVEF': r"(?i)LVEF.*?[:：]\s*(\d+\.?\d*)",
            'LVEDV': r"(?i)LVEDV.*?[:：]\s*(\d+\.?\d*)",
            'LVESV': r"(?i)LVESV.*?[:：]\s*(\d+\.?\d*)",
            'SV': r"(?i)\bSV\b.*?[:：]\s*(\d+\.?\d*)", # \b to avoid matching LVESV
            'LVEDD': r"(?i)LVEDD.*?[:：]\s*(\d+\.?\d*)",
            'IVS': r"(?i)IVS.*?[:：]\s*(\d+\.?\d*)",
            'LVPW': r"(?i)LVPW.*?[:：]\s*(\d+\.?\d*)",
            'RWT': r"(?i)RWT.*?[:：]\s*(\d+\.?\d*)",
            'RVEF': r"(?i)RVEF.*?[:：]\s*(\d+\.?\d*)",
            'RVEDV': r"(?i)RVEDV.*?[:：]\s*(\d+\.?\d*)",
            'RVESV': r"(?i)RVESV.*?[:：]\s*(\d+\.?\d*)",
            'LAV': r"(?i)LAV.*?[:：]\s*(\d+\.?\d*)",
            'RAV': r"(?i)RAV.*?[:：]\s*(\d+\.?\d*)",
            # SI is tricky, add Chinese label to be specific
            'SI': r"(?i)SI\s*[\(（]球形指数[）\)].*?[:：]\s*(\d+\.?\d*)",
        }

    def parse(self, report_text: str) -> dict:
        """
        Parse report text to extract quantitative metrics.
        Returns a dictionary { 'LVEF': 60.5, ... }
        """
        result = {}
        if not report_text:
            return result

        # Strategy A: Try extracting embedded JSON
        # Some reports might be raw JSON dumps or contain JSON blocks
        json_data = self._extract_json(report_text)
        if json_data:
            result.update(json_data)

        # Strategy B: Regex extraction (Robust path)
        # Preprocess text to remove interference
        clean_text = self._preprocess(report_text)
        
        for key, pattern in self.patterns.items():
            # If not already found via JSON (or if JSON was partial)
            if key not in result:
                match = re.search(pattern, clean_text)
                if match:
                    try:
                        result[key] = float(match.group(1))
                    except ValueError:
                        pass
        
        return result

    def _extract_json(self, text):
        """Try to find and parse a JSON block in the text."""
        try:
            # Check if the whole text is JSON first
            if text.strip().startswith('{') and text.strip().endswith('}'):
                data = json.loads(text)
                return self._flatten_json_metrics(data)
            
            # Search for JSON block
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                json_str = text[start:end+1]
                data = json.loads(json_str)
                return self._flatten_json_metrics(data)
        except:
            pass
        return None

    def _preprocess(self, text):
        """Clean text for better regex matching."""
        # Remove Markdown bold/italic
        text = text.replace('**', '').replace('__', '')
        # Normalize full-width spaces
        text = text.replace('\u3000', ' ')
        return text

    def _flatten_json_metrics(self, data):
        """
        Flatten specific JSON structures (like 'requested_metrics' list)
        into a simple key-value dict.
        """
        metrics = {}
        
        # Case 1: Simple key-value (unlikely but possible)
        # Case 2: 'requested_metrics' list (seen in example 0000509158)
        if isinstance(data, dict):
            if 'requested_metrics' in data and isinstance(data['requested_metrics'], list):
                for item in data['requested_metrics']:
                    if isinstance(item, dict) and 'name' in item and 'value' in item:
                        metrics[item['name']] = item['value']
            
            # Case 3: 'raw_measurements' (deeply nested) - maybe too complex to map automatically
            # Let's stick to high-level metrics for now.
            
        return metrics
