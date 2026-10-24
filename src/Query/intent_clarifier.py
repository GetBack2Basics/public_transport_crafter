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

    def __init__(self):
        pass

    def extract_route_numbers(self, text: str) -> List[str]:
        """Extracts route designators like '275', '270', '269', 'CCN', 'T1', 'HUN', 'M1', 'B1'."""
        tokens = re.findall(r"\b([A-Z]{1,3}\d{0,2}|\d{1,4}[A-Za-z]?)\b", text, re.IGNORECASE)
        # Filter common non-route stop/time words
        ignore = {"AND", "OR", "TO", "FROM", "IN", "AT", "THE", "IS", "ON", "OF", "WITH", "FOR", "BUS", "TRAIN", "MIN", "MINS", "STATION"}
        routes = []
        for t in tokens:
            t_upper = t.upper()
            if t_upper not in ignore and (re.match(r"^\d{2,4}$", t) or t_upper in {"CCN", "HUN", "BMT", "SCO", "T1", "T2", "T4", "T9", "M1", "B1"}):
                if t_upper not in routes:
                    routes.append(t_upper)
        return routes

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

        # 1. Route validation
        if len(routes) == 0:
            clarifications_needed.append({
                "parameter": "routes",
                "question": "Which specific bus route or train line would you like to optimize?",
                "options": ["Route 275 (Lake Macquarie)", "Route 270 (Toronto-Newcastle)", "CCN Train (Central Coast & Newcastle)", "Other"]
            })
        elif len(routes) == 1:
            r = routes[0]
            # Route collision check (e.g. 275 in Hunter vs Sydney)
            if r in ["275", "270", "269"] and not detected_region:
                clarifications_needed.append({
                    "parameter": "route_agency",
                    "question": f"Route {r} exists in multiple regions across NSW. Which operator/corridor do you mean?",
                    "options": [
                        f"Route {r} (Lake Macquarie / Hunter Valley - CDC Hunter)",
                        f"Route {r} (Sydney Metropolitan - Forest Coach Lines / North Shore)"
                    ]
                })

            clarifications_needed.append({
                "parameter": "connecting_route",
                "question": f"Which connecting service should Route {r} coordinate with?",
                "options": [
                    "CCN Train (Central Coast & Newcastle Line)",
                    "Route 270 (Toronto-Newcastle Bus)",
                    "Route 269 (Toronto-Charlestown Bus)"
                ]
            })

        # 2. Station / Interchange validation
        if len(stations) == 0:
            clarifications_needed.append({
                "parameter": "interchange",
                "question": "At which station or interchange should the transfer be synchronized?",
                "options": [
                    "Morisset Station Interchange",
                    "Fassifern Station Interchange",
                    "Old Toronto Station Interchange (Victory Parade)",
                    "All shared stops along the route"
                ]
            })
        elif len(stations) > 1 and "and" in q_lower:
            # Multi-station mentioned (e.g. Morisset and Fassifern)
            # This is acceptable and means optimize across both
            pass

        # 3. Transfer window confirmation (if custom phrasing detected)
        window_specified = bool(re.search(r"\d{1,2}\s*(?:-|to)\s*\d{1,2}\s*min", q_lower))

        is_complete = len(clarifications_needed) == 0

        return {
            "raw_query": q,
            "detected_routes": routes,
            "detected_stations": stations,
            "detected_region": detected_region or "hunter",
            "transfer_window": {"min_minutes": min_buf, "max_minutes": max_buf, "explicit": window_specified},
            "is_complete": is_complete,
            "clarifications_needed": clarifications_needed
        }
