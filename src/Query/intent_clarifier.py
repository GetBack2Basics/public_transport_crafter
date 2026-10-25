#!/usr/bin/env python3
"""
src/Query/intent_clarifier.py
Natural Language Transit Query Intent Parser and Clarification Dialog Engine.
Analyzes user transit requests, detects underspecified parameters or multi-region ambiguities
(e.g., route number collisions across NSW, multiple interchange stations, desired transfer windows),
and generates structured clarifying questions before executing complex SQL against GCS.
"""

import re
from typing import Dict, Any, List, Optional, Tuple


# Authority table of known NSW transit operators and major regional hubs
REGION_HINTS = {
    "hunter": ["hunter", "newcastle", "lake macquarie", "toronto", "morisset", "fassifern", "maitland", "cessnock", "charlestown", "wallsend", "glendale"],
    "sydney": ["sydney", "central", "parramatta", "chatswood", "hornsby", "terrey hills", "qvb", "castlecrag", "barangaroo", "tallawong", "b-line", "mona vale"],
    "central_coast": ["gosford", "wyong", "tuggerah", "woy woy"],
    "illawarra": ["wollongong", "shellharbour", "uow", "kiama", "thirroul"],
    "blue_mountains": ["katoomba", "springwood", "penrith", "lithgow"]
}


class IntentClarifier:
    """Parses natural language transit queries and generates clarifying questions when ambiguous."""

    def __init__(self, index_path: Optional[str] = "data/lake/nsw_route_lookup_index.json"):
        import json
        from pathlib import Path
        self.route_index: Dict[str, Any] = {}
        if index_path and Path(index_path).exists():
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    self.route_index = json.load(f)
            except Exception:
                self.route_index = {}

    def extract_route_numbers(self, text: str) -> List[str]:
        """Extracts any route designator like '99', '275', '852', '181', '9999', 'CCN', 'T1', 'B1'."""
        # 1. Explicit syntax
        explicit_match = re.search(r"(?:route|bus|line|train|service|feeder)\s*[:#]?\s*([a-z0-9]{1,7})\b", text, re.IGNORECASE)
        explicit_route = explicit_match.group(1).upper() if explicit_match else None

        tokens = re.findall(r"\b([A-Za-z0-9]{1,7})\b", text)
        ignore = {
            "AND", "OR", "TO", "FROM", "IN", "AT", "THE", "IS", "ON", "OF", "WITH", "FOR", 
            "BUS", "TRAIN", "MIN", "MINS", "STATION", "HOW", "CAN", "WE", "OPTIMIZE", "CONNECT",
            "EXAMPLE", "GIVEN", "SOLVE", "CHECK", "NUMBER", "POSSIBLE", "ROUTE", "ROUTES",
            "SAY", "THAT", "NEAREST", "EXIST", "EXISTS", "DOESNT", "JUST", "EVER", "DONT"
        }
        routes = []
        if explicit_route and explicit_route not in ignore:
            routes.append(explicit_route)

        for t in tokens:
            t_upper = t.upper()
            if t_upper in ignore or t_upper in routes:
                continue
            # Route numbers with digits (e.g. 99, 275, 852, 9999, 160X)
            if any(c.isdigit() for c in t):
                routes.append(t_upper)
            # Known transit lines
            elif t_upper in {"CCN", "HUN", "BMT", "SCO", "SHL", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "M1", "B1", "NLR", "L1", "L2", "L3", "F1", "F2", "F3", "F4"}:
                routes.append(t_upper)
        return routes

    def levenshtein_distance(self, s1: str, s2: str) -> int:
        """Computes Levenshtein distance between two strings."""
        if len(s1) < len(s2):
            return self.levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr = [i + 1]
            for j, c2 in enumerate(s2):
                ins = prev[j + 1] + 1
                d = curr[j] + 1
                sub = prev[j] + (0 if c1 == c2 else 1)
                curr.append(min(ins, d, sub))
            prev = curr
        return prev[-1]

    def find_nearest_routes(self, target: str, limit: int = 5) -> List[str]:
        """Calculates nearest available routes across 10,266 routes if queried route does not exist."""
        if not self.route_index:
            return []
        t = target.lower().strip()
        t_digits = ''.join(c for c in t if c.isdigit())
        t_num = int(t_digits) if t_digits else None

        scored = []
        for k, item in self.route_index.items():
            score = 0
            k_digits = ''.join(c for c in k if c.isdigit())
            k_num = int(k_digits) if k_digits else None

            # Substring match bonus
            if k in t or t in k:
                score -= 12

            # Suffix match bonus (e.g. both end in 99)
            if len(t) >= 2 and k.endswith(t):
                score -= 15
            elif len(k) >= 2 and t.endswith(k):
                score -= 10

            # Edit distance penalty
            lev = self.levenshtein_distance(t, k)
            score += lev * 3

            # Numeric proximity bonus
            if t_num is not None and k_num is not None:
                diff = abs(t_num - k_num)
                if diff < 10:
                    score -= 8
                elif diff < 50:
                    score -= 4

            trip_sum = sum(c.get('trip_count', 0) for c in item.get('corridors', []))
            scored.append((score, -trip_sum, item.get('route_short_name', k.upper())))

        scored.sort()
        return [s[2] for s in scored[:limit]]

    def extract_transfer_window(self, text: str) -> Tuple[int, int]:
        """Extracts desired transfer buffer window (e.g. '5-15 mins', '4 to 10 minutes'). Defaults to (5, 15)."""
        match = re.search(r"(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s*(?:min|minute|mins)", text, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))
        return 5, 15

    def extract_station_hints(self, text: str) -> List[str]:
        """Extracts potential station or interchange mentions."""
        text_lower = text.lower()
        known_stations = [
            "morisset", "fassifern", "toronto", "newcastle", "maitland", "hornsby",
            "chatswood", "central", "parramatta", "gosford", "wyong", "wollongong",
            "katoomba", "dubbo", "lithgow", "tallawong", "barangaroo", "charlestown"
        ]
        found = [stn.title() for stn in known_stations if stn in text_lower]
        return found

    def analyze_intent(self, user_query: str) -> Dict[str, Any]:
        """
        Analyzes natural language query and determines if all required parameters are resolved,
        or if clarifying questions must be asked before generating SQL.
        """
        q = user_query.strip()
        routes = self.extract_route_numbers(q)
        stations = self.extract_station_hints(q)
        min_buf, max_buf = self.extract_transfer_window(q)

        # Detect regional context
        q_lower = q.lower()
        detected_region = None
        for region, hints in REGION_HINTS.items():
            if any(h in q_lower for h in hints):
                detected_region = region
                break

        clarifications_needed = []
        route_status = {}

        # 1. Route validation
        if len(routes) == 0:
            sample_routes = []
            if self.route_index:
                # Pick top active routes by trip count
                sorted_routes = sorted(
                    self.route_index.values(),
                    key=lambda x: sum(c.get("trip_count", 0) for c in x.get("corridors", [])),
                    reverse=True
                )
                sample_routes = [f"Route {r['route_short_name']}" for r in sorted_routes[:5]]
            if not sample_routes:
                sample_routes = ["Route 333", "Route B1", "Route T1", "Route 275", "Route 852"]

            clarifications_needed.append({
                "parameter": "routes",
                "question": "Which specific bus route or train line would you like to optimize?",
                "options": sample_routes
            })
        else:
            for r in routes:
                r_key = r.lower()
                if self.route_index:
                    if r_key not in self.route_index:
                        nearest = self.find_nearest_routes(r, 5)
                        route_status[r] = {
                            "exists": False,
                            "nearest_options": nearest,
                            "message": f"Route {r} does not exist in the NSW transit lakehouse (10,266 routes ingested)."
                        }
                        clarifications_needed.append({
                            "parameter": "route_not_found",
                            "question": f"Route {r} was not found in the NSW transit lakehouse. Did you mean one of the nearest operating routes?",
                            "options": [f"Route {opt}" for opt in nearest]
                        })
                    else:
                        route_info = self.route_index[r_key]
                        corridors = route_info.get("corridors", [])
                        route_status[r] = {
                            "exists": True,
                            "corridors": corridors
                        }
                        if len(corridors) > 1 and not detected_region:
                            clarifications_needed.append({
                                "parameter": "route_agency",
                                "question": f"Multiple Route {r} services operate in NSW ({len(corridors)} corridors). Which operator do you want to plan?",
                                "options": [f"{c['agency_name']}: {c['route_long_name']}" for c in corridors]
                            })
                else:
                    # Fallback if index not provided
                    route_status[r] = {"exists": True}

        # 2. Station / Interchange validation
        if len(stations) == 0 and not any(rs.get("exists") is False for rs in route_status.values()):
            # Dynamically derive candidate interchange options from detected route corridors if available
            interchange_options = []
            if routes and self.route_index:
                first_r = routes[0].lower()
                if first_r in self.route_index:
                    for c in self.route_index[first_r].get("corridors", []):
                        long_n = c.get("route_long_name", "")
                        if " to " in long_n:
                            parts = long_n.split(" to ")
                            for p in parts:
                                p_clean = p.split(" via ")[0].strip()
                                if p_clean and f"{p_clean} Interchange" not in interchange_options:
                                    interchange_options.append(f"{p_clean} Interchange")
            if not interchange_options:
                interchange_options = ["Major Connecting Station Interchange", "All shared stops along the route"]
            else:
                interchange_options.append("All shared stops along the route")

            clarifications_needed.append({
                "parameter": "interchange",
                "question": "At which station or interchange should the transfer be synchronized?",
                "options": interchange_options[:5]
            })

        window_specified = bool(re.search(r"\d{1,2}\s*(?:-|to)\s*\d{1,2}\s*min", q_lower))
        is_complete = len(clarifications_needed) == 0

        # Infer region dynamically from route corridors if not explicitly mentioned
        if not detected_region and routes and self.route_index:
            first_r = routes[0].lower()
            if first_r in self.route_index:
                corrs = self.route_index[first_r].get("corridors", [])
                if corrs:
                    agency = corrs[0].get("agency_name", "").lower()
                    if "hunter" in agency or "newcastle" in agency:
                        detected_region = "hunter"
                    elif "illawarra" in agency or "wollongong" in agency:
                        detected_region = "illawarra"
                    elif "blue mountains" in agency:
                        detected_region = "blue_mountains"
                    elif "central coast" in agency:
                        detected_region = "central_coast"
                    elif "sydney" in agency or "transit systems" in agency or "interline" in agency or "forest" in agency or "metro" in agency:
                        detected_region = "sydney"

        return {
            "raw_query": q,
            "detected_routes": routes,
            "route_status": route_status,
            "detected_stations": stations,
            "detected_region": detected_region or "statewide",
            "transfer_window": {"min_minutes": min_buf, "max_minutes": max_buf, "explicit": window_specified},
            "is_complete": is_complete,
            "clarifications_needed": clarifications_needed
        }
