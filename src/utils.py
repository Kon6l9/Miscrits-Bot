# src/utils.py

# Grade ranking (old system, still supported)
RANK_ORDER = ["C","C+","B","B+","A","A+","S","S+"]

# IP Rating ranking (new system) - from strongest to weakest
IP_RATINGS_ORDER = ["S+", "S", "A+", "A", "B+", "B", "C+", "C", "D+", "D", "F+", "F", "F-"]

# Rarity list
RARITIES = ["Common","Rare","Epic","Exotic","Legendary"]


def rank_index(r):
    """Get index of grade rank (old system)"""
    try:
        return RANK_ORDER.index(r)
    except Exception:
        return -1


def rank_ge(found, minimum):
    """Check if found grade >= minimum grade (old system)"""
    if minimum == "All":
        return True
    if not found:
        return False
    return rank_index(found) >= rank_index(minimum)


def ip_rating_index(rating: str) -> int:
    """Get index of IP rating (lower index = stronger)"""
    try:
        return IP_RATINGS_ORDER.index(rating)
    except (ValueError, AttributeError):
        return 999  # Unknown rating is weakest


def ip_rating_meets_minimum(found: str, minimum: str) -> bool:
    """
    Check if found IP rating meets minimum requirement
    
    Args:
        found: The detected IP rating (e.g., "S+", "A", "B+")
        minimum: The minimum required rating (e.g., "A", "B+ and Below")
    
    Returns:
        True if found meets or exceeds minimum
    
    Examples:
        ip_rating_meets_minimum("S+", "A") -> True
        ip_rating_meets_minimum("B+", "A") -> False
        ip_rating_meets_minimum("A+", "A") -> True
        ip_rating_meets_minimum("S", "S") -> True
    """
    if not found or not minimum:
        return False
    
    # Special case: "B+ and Below" accepts anything B+ or lower
    if minimum == "B+ and Below":
        return found in ["B+", "B", "C+", "C", "D+", "D", "F+", "F"]
    
    # Normal comparison: lower index = stronger
    found_idx = ip_rating_index(found)
    min_idx = ip_rating_index(minimum)
    
    # found must be same or stronger (same or lower index)
    return found_idx <= min_idx


def format_ip_rating(rating: str) -> str:
    """Format IP rating with emoji indicators"""
    indicators = {
        "S+": "🌟",
        "S": "⭐",
        "A+": "🔥",
        "A": "✨",
        "B+": "💫",
        "B": "⚡",
        "C+": "💥",
        "C": "✦",
        "D+": "•",
        "D": "·",
        "F+": "·",
        "F": "·"
    }
    icon = indicators.get(rating, "?")
    return f"{icon} {rating}"


def format_rarity(rarity: str) -> str:
    """Format rarity with emoji indicators"""
    indicators = {
        "Legendary": "👑",
        "Exotic": "💎",
        "Epic": "🔮",
        "Rare": "💠",
        "Common": "⚪"
    }
    icon = indicators.get(rarity, "?")
    return f"{icon} {rarity}"


def validate_skill_number(skill_name: str) -> bool:
    """Validate skill name format (e.g., 'Skill 1', 'Skill 12')"""
    try:
        if not skill_name.startswith("Skill "):
            return False
        num = int(skill_name.split()[-1])
        return 1 <= num <= 12
    except (ValueError, IndexError):
        return False


def get_skill_strength_category(skill_name: str) -> str:
    """Get skill strength category for logging"""
    try:
        num = int(skill_name.split()[-1])
        if num <= 3:
            return "HIGH"
        elif num <= 8:
            return "MEDIUM"
        else:
            return "LOW"
    except (ValueError, IndexError):
        return "UNKNOWN"