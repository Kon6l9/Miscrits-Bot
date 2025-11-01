
RANK_ORDER = ["C","C+","B","B+","A","A+","S","S+"]
def rank_index(r):
    try:
        return RANK_ORDER.index(r)
    except Exception:
        return -1

def rank_ge(found, minimum):
    if minimum == "All":
        return True
    if not found:
        return False
    return rank_index(found) >= rank_index(minimum)


RARITIES = ["Common","Rare","Epic","Exotic","Legendary"]
