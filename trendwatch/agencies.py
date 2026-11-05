"""National news agencies, grouped by country and ownership type.

kind: "state"       -> state-run, state-owned or government-run (group: "<Country> state-linked media")
      "public"      -> public corporations / publicly funded (group: "<Country> public media")
      "independent" -> cooperatives, non-profits, private wires (group: "<Country> independent media")

Names and domains were written from memory, not verified one by one. A wrong or missing domain only
means that agency is matched by name instead, or not found; run check_sources.py to see what works.
Edit this list freely. Short ambiguous acronyms (CNA, MAP, INA, ...) are deliberately left out.
"""

# (country, kind, [outlet names as they may appear in results], [domains])
AGENCIES = [
    ("Algeria", "state", ["Algérie Presse Service", "Algerie Presse Service"], ["aps.dz"]),
    ("Argentina", "state", ["Télam", "Telam"], []),  # reported closed in 2024; kept for old articles
    ("Australia", "independent", ["Australian Associated Press", "AAP"], ["aap.com.au"]),
    ("Austria", "independent", ["Austria Presse Agentur", "APA"], ["apa.at"]),
    ("Azerbaijan", "state", ["AZERTAC", "Azerbaijan State News Agency"], ["azertag.az"]),
    ("Bahrain", "state", ["Bahrain News Agency"], ["bna.bh"]),
    ("Bangladesh", "state", ["Bangladesh Sangbad Sangstha"], ["bssnews.net"]),
    ("Belgium", "independent", ["Belga News Agency", "Belga"], ["belganewsagency.eu"]),
    ("Brazil", "public", ["Agência Brasil", "Agencia Brasil"], ["agenciabrasil.ebc.com.br"]),
    ("Bulgaria", "public", ["Bulgarian News Agency", "BTA"], ["bta.bg"]),
    ("Canada", "independent", ["The Canadian Press", "Canadian Press"], ["thecanadianpress.com"]),
    ("China", "state", ["Xinhua News Agency", "Xinhua", "Xinhua Net"], ["xinhuanet.com", "news.cn"]),
    ("Croatia", "public", ["Croatian News Agency", "HINA"], ["hina.hr"]),
    ("Cuba", "state", ["Prensa Latina"], ["plenglish.com", "prensa-latina.cu"]),
    ("Czech Republic", "public", ["Czech News Agency", "ČTK"], ["ctk.cz"]),
    ("Denmark", "independent", ["Ritzau", "Ritzau Bureau"], ["ritzau.dk"]),
    ("Egypt", "state", ["Middle East News Agency"], ["mena.org.eg"]),
    ("Finland", "independent", ["STT", "Finnish News Agency STT"], ["stt.fi"]),
    ("France", "public", ["Agence France-Presse", "AFP", "France-Presse"], ["afp.com"]),
    ("Germany", "independent", ["Deutsche Presse-Agentur", "dpa"], ["dpa.com", "dpa-international.com"]),
    ("Greece", "public", ["Athens-Macedonian News Agency", "AMNA"], ["amna.gr"]),
    ("Hungary", "public", ["Magyar Távirati Iroda", "MTI"], ["mti.hu"]),
    ("India", "independent", ["Press Trust of India", "PTI"], ["ptinews.com"]),
    ("Indonesia", "state", ["Antara", "Antara News"], ["antaranews.com"]),
    ("Iran", "state", ["Islamic Republic News Agency", "IRNA", "Tasnim News Agency", "Tasnim",
                       "Fars News Agency", "Fars News"],
     ["irna.ir", "tasnimnews.ir", "farsnews.ir"]),
    ("Iraq", "state", ["Iraqi News Agency"], ["ina.iq"]),
    ("Italy", "independent", ["ANSA", "ANSA.it", "Agenzia Nazionale Stampa Associata"], ["ansa.it"]),
    ("Japan", "independent", ["Kyodo News", "Kyodo"], ["kyodonews.net"]),
    ("Jordan", "state", ["Jordan News Agency", "Petra", "Petra News Agency"], ["petra.gov.jo"]),
    ("Kazakhstan", "state", ["Kazinform", "Kazinform International News Agency"], ["inform.kz"]),
    ("Kenya", "state", ["Kenya News Agency"], ["kenyanews.go.ke"]),
    ("Kuwait", "state", ["Kuwait News Agency", "KUNA"], ["kuna.net.kw"]),
    ("Malaysia", "public", ["Bernama"], ["bernama.com"]),
    ("Morocco", "state", ["Maghreb Arabe Presse", "MAP Express"], ["mapnews.ma"]),
    ("Netherlands", "independent", ["Algemeen Nederlands Persbureau", "ANP"], ["anp.nl"]),
    ("Nigeria", "state", ["News Agency of Nigeria"], ["nannews.ng"]),
    ("North Korea", "state", ["Korean Central News Agency", "KCNA"], []),
    ("Norway", "independent", ["Norsk Telegrambyrå", "NTB"], ["ntb.no"]),
    ("Pakistan", "state", ["Associated Press of Pakistan"], ["app.com.pk"]),
    ("Philippines", "state", ["Philippine News Agency"], ["pna.gov.ph"]),
    ("Poland", "public", ["Polish Press Agency", "PAP"], ["pap.pl"]),
    ("Portugal", "public", ["Lusa", "Lusa News Agency"], ["lusa.pt"]),
    ("Qatar", "state", ["Qatar News Agency", "QNA", "Al Jazeera", "Al Jazeera English",
                        "Al Jazeera Media Network"], ["qna.org.qa", "aljazeera.com"]),
    ("Romania", "public", ["AGERPRES"], ["agerpres.ro"]),
    ("Russia", "state", ["TASS", "TASS Russian News Agency", "RT", "RT News", "RT English",
                         "Russia Today"], ["tass.com", "rt.com", "rt-english.com"]),
    ("Saudi Arabia", "state", ["Saudi Press Agency"], ["spa.gov.sa"]),
    ("Serbia", "independent", ["Beta News Agency"], ["beta.rs"]),
    ("South Korea", "public", ["Yonhap News Agency", "Yonhap"], ["yna.co.kr"]),
    ("Spain", "state", ["Agencia EFE", "EFE", "EFE News Services", "EFE Noticias"], ["efe.com"]),
    ("Sweden", "independent", ["Tidningarnas Telegrambyrå", "TT News Agency"], ["tt.se"]),
    ("Switzerland", "independent", ["Keystone-SDA", "Keystone SDA"], ["keystone-sda.ch"]),
    ("Syria", "state", ["Syrian Arab News Agency", "SANA"], ["sana.sy"]),
    ("Taiwan", "public", ["Central News Agency", "Focus Taiwan"], ["focustaiwan.tw", "cna.com.tw"]),
    ("Turkey", "state", ["Anadolu Agency", "Anadolu Ajansı", "Anadolu"], ["aa.com.tr"]),
    ("Ukraine", "state", ["Ukrinform"], ["ukrinform.net"]),
    ("United Arab Emirates", "state", ["Emirates News Agency", "WAM"], ["wam.ae"]),
    ("United Kingdom", "independent", ["Reuters", "PA Media", "Press Association"],
     ["reuters.com", "pa.media"]),
    ("United States", "independent", ["Associated Press", "The Associated Press", "AP News", "AP"],
     ["apnews.com"]),
    ("Vietnam", "state", ["Vietnam News Agency", "VNA"], ["vnanet.vn"]),
]

LABEL = {"state": "state-linked", "public": "public", "independent": "independent"}


def group_name(country, kind):
    return f"{country} {LABEL[kind]} media"


def outlet_groups():
    out = {}
    for country, kind, names, _ in AGENCIES:
        out.setdefault(group_name(country, kind), []).extend(names)
    return out


def domain_groups():
    return {d: group_name(country, kind) for country, kind, _, domains in AGENCIES for d in domains}


def site_domains():
    return [d for _, _, _, domains in AGENCIES for d in domains]
