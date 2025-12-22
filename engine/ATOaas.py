import json
import sys
import time
from pathlib import Path

# ─── Helpers for color output ────────────────────────────
class Color:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RESET = "\033[0m"

def printc(text, color=Color.RESET):
    print(f"{color}{text}{Color.RESET}")

system_id = input("Enter System ID: ").strip()
data_path = Path(input("Enter path to the data report file: ").strip())
checklist_path = Path(input("Enter path to the checklist file: ").strip())

# ─── Variables ──────────────────────────────────────────
# directory where this script file lives
BASE_DIR = Path(__file__).resolve().parent

# "Notionalassets" folder next to the script
DemoAssets = BASE_DIR / "Notionalassets"


start_time = time.time()

# ─── Company Logo ───────────────────────────────────────
logoart = r"""
           #####                                                          
          #######                                                         
 **       #######                                                         
***********##### *******                                                  
 ***********************                                                  
       ===************                                                    
    ======== ****     **********    *           *********  ****       ****
   ====        ***   ************ ****        ************  *****   ***** 
 ===            **   ***      ********        ****           **********   
==              **   *****************        ***********      *******    
               **    ************ ****        ****            *********   
              *      ***          *********** ************  *****  ****** 
                     ***          *********** ***********  *****     *****
"""
print()
printc(logoart, Color.GREEN)
printc("TECTIX", Color.GREEN)
printc("Version: 2.4 - 3DEC2025", Color.GREEN)
printc("PLEX Solutions LLC", Color.GREEN)
printc("John Weise, Richard Trapp, Logan Loyack", Color.GREEN)
print()
printc(f"System ID: {system_id}", Color.CYAN)
printc(f"data Report Path: {data_path}", Color.CYAN)
printc(f"Checklist Path: {checklist_path}", Color.CYAN)

# ─── Pause ──────────────────────────────────────────────
time.sleep(1)

# ─── Initial API connection check ───────────────────────
try:
    with open(DemoAssets / "InitialTest.json", "r", encoding="utf-8") as f:
        connectresult = json.load(f)
    connectcode = str(connectresult["meta"]["code"])
except Exception as e:
    printc(f"Failed to load InitialTest.json: {e}", Color.RED)
    sys.exit(1)

if connectcode == "200":
    printc(f"Connection to the eMASS API is successful with code {connectcode}", Color.GREEN)
else:
    printc(f"Connection to the API failed with code {connectcode}", Color.RED)
    printc("Check the API key and Cert thumbprint", Color.YELLOW)
    sys.exit(1)

# ─── Check if data report file exists ───────────────────
if Path(data_path).exists():
    printc(f"Data File Found at location: {data_path}", Color.GREEN)
else:
    printc("Unable to locate data Report at provided file location.", Color.RED)
    printc("Verify the data Report file location", Color.YELLOW)
    sys.exit(1)

# ─── Check if checklist file exists ─────────────────────
if Path(checklist_path).exists():
    printc(f"Blank Checklist File Found at location: {checklist_path}", Color.GREEN)
else:
    printc("Unable to locate blank checklist at provided file location.", Color.RED)
    printc("Verify the file location", Color.YELLOW)
    sys.exit(1)

#pull data
# Load SystemInfo.json (make sure this is above)
with open(DemoAssets / "SystemInfo.json", "r", encoding="utf-8") as f:
    systemdatademo = json.load(f)

records = systemdatademo.get("data", [])

# --- SIMPLE & ROBUST: compare as strings, no typed_id needed ---
systemdata = next(
    (x for x in records if str(x.get("systemId")) == str(system_id).strip()),
    None
)
print()
if systemdata is None:
    available = [x.get("systemId") for x in records]
    printc(f"No system found with ID {system_id!r}", Color.RED)
    printc(f"Available IDs: {available}", Color.YELLOW)
    sys.exit(1)

# Safe to access
systemname        = systemdata.get("name")
systemACR         = systemdata.get("acronym")
systemDescription = systemdata.get("description")
systemVersion     = systemdata.get("versionReleaseNo")
print()
printc(f"System ID:          {system_id}", Color.CYAN)
printc(f"System Name:        {systemname}", Color.CYAN)
printc(f"System Acronym:     {systemACR}", Color.CYAN)
printc(f"System Version:     {systemVersion}", Color.CYAN)
print()
printc(f"System Description: {systemDescription}", Color.CYAN)
print()



