"""Curated built-in library of classic melodies in ABC notation for instant & offline use."""

from typing import List, Dict, Optional

BUILTIN_SONGS: List[Dict[str, str]] = [
    {
        "id": "builtin:happy-birthday",
        "title": "Happy Birthday to You",
        "artist": "Traditional (Key of F Major — tests auto-transposition to C!)",
        "source": "builtin",
        "badge": "F Major → C Major",
        "abc": """X:1
T:Happy Birthday to You
M:3/4
L:1/4
Q:1/4=120
K:F
C/2C/2 | D C F | E2 C/2C/2 | D C G | F2 C/2C/2 |
c A F | E D _B/2_B/2 | A F G | F2 |]
""",
    },
    {
        "id": "builtin:ode-to-joy",
        "title": "Ode to Joy (Symphony No. 9)",
        "artist": "Ludwig van Beethoven (G Major → C Major)",
        "source": "builtin",
        "badge": "G Major → C Major",
        "abc": """X:2
T:Ode to Joy
M:4/4
L:1/4
Q:1/4=120
K:G
B B c d | d c B A | G G A B | B3/2 A/2 A2 |
B B c d | d c B A | G G A B | A3/2 G/2 G2 |
A A B G | A B/2c/2 B G | A B/2c/2 B A | G A D2 |
B B c d | d c B A | G G A B | A3/2 G/2 G2 |]
""",
    },
    {
        "id": "builtin:twinkle-star",
        "title": "Twinkle, Twinkle, Little Star",
        "artist": "Traditional (C Major — direct 15-note fit)",
        "source": "builtin",
        "badge": "C Major (Native)",
        "abc": """X:3
T:Twinkle Twinkle Little Star
M:4/4
L:1/4
Q:1/4=112
K:C
C C G G | A A G2 | F F E E | D D C2 |
G G F F | E E D2 | G G F F | E E D2 |
C C G G | A A G2 | F F E E | D D C2 |]
""",
    },
    {
        "id": "builtin:fur-elise",
        "title": "Für Elise (Main Theme)",
        "artist": "Ludwig van Beethoven (A Minor w/ Chromatics — tests Scale Warning!)",
        "source": "builtin",
        "badge": "Chromatic Warning Demo",
        "abc": """X:4
T:Fur Elise
M:3/8
L:1/16
Q:1/8=132
K:Amin
e^d | e^deB=dc | A2 zCEA | B2 zE^GB | c2 ze^d |
e^deB=dc | A2 zCEA | B2 zEcB | A4 Bc |
d2 zGfe | e2 zFed | d2 zEdc | B4 e^d |
e^deB=dc | A2 zCEA | B2 zEcB | A4 |]
""",
    },
    {
        "id": "builtin:greensleeves",
        "title": "Greensleeves",
        "artist": "Traditional English (A Dorian/Minor w/ F# & G#)",
        "source": "builtin",
        "badge": "Minor / Modal Demo",
        "abc": """X:5
T:Greensleeves
M:6/8
L:1/8
Q:3/8=55
K:Amin
A | c2 d e>fe | d2 B G>AB | c2 A A>^GA | B2 ^G E2 A |
c2 d e>fe | d2 B G>AB | c>BA ^G>^FG | A3 A2 z |
g3 g>fe | d2 B G>AB | c2 A A>^GA | B2 ^G E3 |
g3 g>fe | d2 B G>AB | c>BA ^G>^FG | A3 A2 |]
""",
    },
    {
        "id": "builtin:canon-in-d",
        "title": "Canon in D (Melody & Arpeggio)",
        "artist": "Johann Pachelbel (D Major → C Major)",
        "source": "builtin",
        "badge": "D Major → C Major",
        "abc": """X:6
T:Canon in D
M:4/4
L:1/8
Q:1/4=84
K:D
f4 e4 | d4 c4 | B4 A4 | B4 c4 |
f2 a2 e2 g2 | d2 f2 c2 e2 | B2 d2 A2 c2 | B2 d2 c2 e2 |
dcdf AGAB | F2 A2 E2 G2 | FGFE D2 F2 | G2 B2 A2 c2 |
f2 fg f2 FG | ABAG AFdc | B2 d2 Bcde | f4 d4 |]
""",
    },
    {
        "id": "builtin:brahms-lullaby",
        "title": "Brahms' Lullaby (Wiegenlied)",
        "artist": "Johannes Brahms (Eb Major → C Major)",
        "source": "builtin",
        "badge": "Eb Major → C Major",
        "abc": """X:7
T:Brahms Lullaby
M:3/4
L:1/8
Q:1/4=92
K:Eb
G G | B3 G G2 | B4 G B | e2 d3 c | c2 B2 F G |
A2 F2 F G | A4 F A | d c B2 d2 | e4 E E |
e4 c A | B4 G E | A2 B2 c2 | B4 E E |
e4 c A | B4 G E | A2 G2 F2 | E4 |]
""",
    },
]


def search_builtin(query: str) -> List[dict]:
    q = query.strip().lower()
    results = []
    for item in BUILTIN_SONGS:
        if not q or q in item["title"].lower() or q in item["artist"].lower():
            results.append({
                "id": item["id"],
                "title": item["title"],
                "subtitle": item["artist"],
                "source": "builtin",
                "badge": item["badge"],
                "url": None,
            })
    return results


def get_builtin_by_id(song_id: str) -> Optional[dict]:
    for item in BUILTIN_SONGS:
        if item["id"] == song_id:
            return item
    return None
