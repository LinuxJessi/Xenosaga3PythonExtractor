"""txlangs.py — the language registry's data (read by txtarget.py).

Pure data: one line per language or written form. ``txtarget`` turns each
line into a profile and COMPUTES its kind (builtin / script-hybrid /
japanese / script) from the letters against what the retail fonts draw, so
adding a language means adding one line here and nothing else.

Line format (fields separated by ``|``)::

    code | English name | endonym | scripts | letters | regions | note

code     BCP-47 tag: ISO 639-1 where one exists, else ISO 639-3; a written
         form other than the language's usual one gets a script subtag
         (``pa-Arab`` = Punjabi in Shahmukhi, ``oj-Cans`` = Ojibwe syllabics)
scripts  ISO 15924 codes, the one the entry is written in first (others
         are scripts the language also uses, for information)
letters  the letters the language needs on top of its script's core set
         (``SCRIPT_CORE``): for Latin, the letters beyond ASCII a-z in
         lower case (upper case is added by ``str.upper``; write it out only
         where that is wrong, like Turkish İ); for other scripts, extra
         letters. ``=`` first replaces the core set; ``@name`` uses one of
         the generated sets (``txtarget._generated``: Canadian syllabics by
         Unicode character name, the common Hangul/Han/kanji repertoires by
         national standard). Empty = the core set only (ASCII for Latin:
         Swahili, Indonesian, Zulu ... really need nothing else).
regions  ISO 3166 region codes of the main varieties (``pt-BR`` style tags
         are accepted by ``txtarget.profile`` and fall back to the entry)
note     shown to the translator (orthography choices, vertical scripts...)

Letters are listed only where the orthography is standard and well known;
the kind is never written by hand.
"""

# Core letter set per script when an entry lists no "=" replacement.
# A string = those letters; a list of (first, last) code point ranges =
# every letter/mark in them that fontTools assigns to the script.
SCRIPT_CORE = {
    "Latn": "",
    "Cyrl": "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    "Grek": "αβγδεζηθικλμνξοπρστυφχψωςάέήίόύώϊϋΐΰ",
    "Armn": [(0x0531, 0x0556), (0x0561, 0x0587)],
    "Geor": [(0x10D0, 0x10F0)],
    "Hebr": [(0x05D0, 0x05EA)],
    "Arab": [(0x0621, 0x063A), (0x0641, 0x064A)],
    "Syrc": [(0x0710, 0x072C)],
    "Thaa": [(0x0780, 0x07B0)],
    "Nkoo": [(0x07CA, 0x07F5)],
    "Deva": "अआइईउऊऋएऐओऔकखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसहािीुूृेैोौंःँ़्।",
    "Beng": [(0x0981, 0x09CE), (0x09D7, 0x09D7), (0x09DC, 0x09E3)],
    "Guru": [(0x0A01, 0x0A4D), (0x0A59, 0x0A5E), (0x0A70, 0x0A75)],
    "Gujr": [(0x0A81, 0x0ACD), (0x0AE0, 0x0AE3)],
    "Orya": [(0x0B01, 0x0B4D), (0x0B5C, 0x0B63), (0x0B71, 0x0B71)],
    "Taml": [(0x0B82, 0x0BCD), (0x0BD7, 0x0BD7)],
    "Telu": [(0x0C01, 0x0C03), (0x0C05, 0x0C4D), (0x0C55, 0x0C56), (0x0C60, 0x0C63)],   # not U+0C00/0C04 (Unicode 7/11, rare, few fonts)
    "Knda": [(0x0C80, 0x0CCD), (0x0CD5, 0x0CD6), (0x0CE0, 0x0CE3)],
    "Mlym": [(0x0D00, 0x0D4E), (0x0D57, 0x0D57), (0x0D60, 0x0D63), (0x0D7A, 0x0D7F)],
    "Sinh": [(0x0D82, 0x0DDF), (0x0DF2, 0x0DF3)],   # not U+0D81 candrabindu (Unicode 13, rare)
    "Thai": "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรฤลฦวศษสหฬอฮะัาำิีึืฺุู็่้๊๋์เแโใไๅๆ",
    # everyday Lao; the Pali letters added in Unicode 12 (U+0E86 ...) are left out: few fonts have them
    "Laoo": [(0x0E81, 0x0E84), (0x0E87, 0x0E88), (0x0E8A, 0x0E8A), (0x0E8D, 0x0E8D), (0x0E94, 0x0E97),
             (0x0E99, 0x0E9F), (0x0EA1, 0x0EA3), (0x0EA5, 0x0EA5), (0x0EA7, 0x0EA7), (0x0EAA, 0x0EAB),
             (0x0EAD, 0x0EC6), (0x0EC8, 0x0ECD), (0x0EDC, 0x0EDD)],
    "Tibt": [(0x0F40, 0x0F6C), (0x0F71, 0x0F84), (0x0F90, 0x0FBC)],
    "Mymr": [(0x1000, 0x103F)],
    "Ethi": [(0x1200, 0x135A)],
    "Cher": [(0x13A0, 0x13F4)],
    "Cans": [(0x1401, 0x166C), (0x166F, 0x167F)],
    "Khmr": [(0x1780, 0x17D2)],
    "Mong": [(0x1820, 0x1878)],
    "Tglg": [(0x1700, 0x1715)],
    "Bugi": [(0x1A00, 0x1A1B)],
    "Bali": [(0x1B00, 0x1B4C)],
    "Sund": [(0x1B80, 0x1BBF)],
    "Java": [(0xA980, 0xA9C0)],
    "Olck": [(0x1C5A, 0x1C7D)],
    "Mtei": [(0xABC0, 0xABED)],
    "Vaii": [(0xA500, 0xA60C), (0xA610, 0xA61F), (0xA62A, 0xA62B)],
    "Tfng": [(0x2D30, 0x2D67), (0x2D6F, 0x2D6F)],
    "Adlm": [(0x1E900, 0x1E94B)],
    "Yiii": [(0xA000, 0xA48C)],
    "Bamu": [(0xA6A0, 0xA6F1)],
    "Osge": [(0x104D8, 0x104FB)],
    "Hmnp": [(0x1E100, 0x1E13D)],
    "Lisu": [(0xA4D0, 0xA4FD)],
    "Cakm": [(0x11100, 0x11134)],
    "Lana": [(0x1A20, 0x1A7C)],
    "Tavt": [(0xAA80, 0xAAC2)],
    "Sylo": [(0xA800, 0xA82C)],
    "Limb": [(0x1900, 0x193B)],
    "Copt": [(0x2C80, 0x2CE4)],
    "Osma": [(0x10480, 0x1049D)],
    "Rohg": [(0x10D00, 0x10D27)],
    "Hang": "@ko",
    "Hani": "@zh-Hans",
    "Jpan": "@ja",
}

# Scripts written top to bottom in columns. The game prints rows left to
# right, so these can only be shown horizontally here.
VERTICAL = {
    "Mong": "Traditional Mongolian script is written vertically (top to bottom, columns "
            "left to right). This game prints text in horizontal rows, so the letters can "
            "only be shown horizontally in this game (rotated 90°, or written in Cyrillic: "
            "mn).",
    "Phag": "Phags-pa is written vertically; this game can only show it horizontally.",
}

DATA = r"""
# ---------------------------------------------------------------- Europe: Latin
en|English|English|Latn||US GB AU CA IE NZ IN ZA|
fr|French|Français|Latn|àâæçéèêëîïôœùûüÿ«»|FR CA BE CH LU SN CI CM CD|
es|Spanish|Español|Latn|áéíñóúü¿¡«»|ES MX AR CO US 419 CL PE VE|
de|German|Deutsch|Latn|äöüß„“|DE AT CH LI|
it|Italian|Italiano|Latn|àèéìíîòóùú|IT CH SM|
pt|Portuguese|Português|Latn|áâãàçéêíóôõú|PT AO MZ CV|
pt-BR|Portuguese (Brazil)|Português (Brasil)|Latn|áâãàçéêíóôõú|BR|
nl|Dutch|Nederlands|Latn|éëïöüèáóú|NL BE SR|
ca|Catalan|Català|Latn|àçéèíïòóúü·|ES AD|
gl|Galician|Galego|Latn|áéíñóúü|ES|
eu|Basque|Euskara|Latn|ñü|ES FR|
oc|Occitan|Occitan|Latn|àáèéíòóúçïü|FR|
co|Corsican|Corsu|Latn|àèìòùâêîôûäëïöüç|FR|
sc|Sardinian|Sardu|Latn|àèìòù|IT|
fur|Friulian|Furlan|Latn|àâçèêìîòôùû|IT|
lld|Ladin|Ladin|Latn|àáèéëìòóöùü|IT|
rm|Romansh|Rumantsch|Latn|àèéìòùäöü|CH|
an|Aragonese|Aragonés|Latn|áéíñóú|ES|
ast|Asturian|Asturianu|Latn|áéíñóúüḥḷ|ES|
mwl|Mirandese|Mirandés|Latn|áâçéêíóôúũ|PT|
lb|Luxembourgish|Lëtzebuergesch|Latn|äëéè|LU|
fy|West Frisian|Frysk|Latn|âêéôûúäëïöü|NL|
nds|Low German|Plattdüütsch|Latn|äöüß|DE NL|
li|Limburgish|Limburgs|Latn|èéëäöü|NL BE|
wa|Walloon|Walon|Latn|åâçèéêîôûë|BE|
sv|Swedish|Svenska|Latn|åäö|SE FI|
da|Danish|Dansk|Latn|æøå|DK|
no|Norwegian|Norsk|Latn|æøå|NO|
nb|Norwegian Bokmål|Norsk bokmål|Latn|æøåéèêóòâô|NO|
nn|Norwegian Nynorsk|Norsk nynorsk|Latn|æøåéèêóòâô|NO|
is|Icelandic|Íslenska|Latn|áðéíóúýþæö|IS|
fo|Faroese|Føroyskt|Latn|áðíóúýæø|FO|
fi|Finnish|Suomi|Latn|äöåšž|FI|
et|Estonian|Eesti|Latn|äöõüšž|EE|
vro|Võro|Võro|Latn|äöõüšžńľŕ|EE|
krl|Karelian|Karjala|Latn|äöšž|RU FI|
se|Northern Sami|Davvisámegiella|Latn|áčđŋšŧž|NO SE FI|
smj|Lule Sami|Julevsámegiella|Latn|áåäŋ|SE NO|
sma|Southern Sami|Åarjelsaemien|Latn|ïæøåäö|NO SE|
smn|Inari Sami|Anarâškielâ|Latn|âáäčđŋšžå|FI|
sms|Skolt Sami|Nuõrttsääʹmǩiõll|Latn|âčʒǯđǧǥǩŋõšžåäʹ|FI|
ga|Irish|Gaeilge|Latn|áéíóú|IE|
gd|Scottish Gaelic|Gàidhlig|Latn|àèìòù|GB|
gv|Manx|Gaelg|Latn|çÇ|IM|
cy|Welsh|Cymraeg|Latn|âêîôûŵŷäëïöüáéíóúàèìòù|GB|
kw|Cornish|Kernewek|Latn||GB|
br|Breton|Brezhoneg|Latn|âêñùü|FR|
mt|Maltese|Malti|Latn|ċġħżàèìòù|MT|
sq|Albanian|Shqip|Latn|çë|AL XK MK|
ro|Romanian|Română|Latn|ăâîșț|RO MD|
rup|Aromanian|Armãneashti|Latn|ãâăîșțľńáéíóú|GR AL MK|
hu|Hungarian|Magyar|Latn|áéíóöőúüű|HU|
pl|Polish|Polski|Latn|ąćęłńóśźż|PL|
csb|Kashubian|Kaszëbsczi|Latn|ąãéëłńòóôùż|PL|
szl|Silesian|Ślōnskŏ|Latn|ćłńŏōôõśźżů|PL|
cs|Czech|Čeština|Latn|áčďéěíňóřšťúůýž|CZ|
sk|Slovak|Slovenčina|Latn|áäčďéíĺľňóôŕšťúýž|SK|
hsb|Upper Sorbian|Hornjoserbšćina|Latn|čćěłńóřšźž|DE|
dsb|Lower Sorbian|Dolnoserbšćina|Latn|čćěłńóŕšśźž|DE|
sl|Slovenian|Slovenščina|Latn|čšž|SI|
hr|Croatian|Hrvatski|Latn|čćđšž|HR BA|
bs|Bosnian|Bosanski|Latn|čćđšž|BA|
sr-Latn|Serbian (Latin)|Srpski|Latn|čćđšž|RS ME|
cnr|Montenegrin|Crnogorski|Latn|čćđšžśź|ME|
lt|Lithuanian|Lietuvių|Latn|ąčęėįšųūž|LT|
lv|Latvian|Latviešu|Latn|āčēģīķļņšūž|LV|
ltg|Latgalian|Latgaļu|Latn|āčēģīķļņōšūž|LV|
tr|Turkish|Türkçe|Latn|çğıİöşü|TR CY|
az|Azerbaijani|Azərbaycanca|Latn Arab Cyrl|çəğıİöşü|AZ IR|
tk|Turkmen|Türkmençe|Latn|çäžňöşüý|TM|
uz|Uzbek|Oʻzbekcha|Latn Cyrl|ʻʼ|UZ|Latin orthography: oʻ and gʻ are written with ʻ (U+02BB), the apostrophe with ʼ (U+02BC).
kk-Latn|Kazakh (Latin)|Qazaqşa|Latn|äğıİñöşūüұ|KZ|The 2021 Latin alphabet.
crh|Crimean Tatar|Qırımtatarca|Latn Cyrl|çğıİñöşü|UA|
gag|Gagauz|Gagauzca|Latn|äçêıİöşţü|MD|
eo|Esperanto|Esperanto|Latn|ĉĝĥĵŝŭ|001|
la|Latin|Latina|Latn||VA|Classical texts in ASCII; add ā ē ī ō ū for macrons (they need drawn letters).
ia|Interlingua|Interlingua|Latn||001|
vo|Volapük|Volapük|Latn|äöü|001|
rom|Romani|Romani|Latn Cyrl|čšžäćǧ|RO BG HU SK RS|Spelling differs by country; this is the common Latin set.
lad|Ladino|Judeo-español|Latn Hebr|ñ|IL TR|
# ---------------------------------------------------------------- Europe: Cyrillic, Greek
ru|Russian|Русский|Cyrl||RU BY KZ KG UA|
uk|Ukrainian|Українська|Cyrl|=абвгґдеєжзиіїйклмнопрстуфхцчшщьюя’|UA|
be|Belarusian|Беларуская|Cyrl|=абвгдеёжзійклмнопрстуўфхцчшыьэюя’|BY|
bg|Bulgarian|Български|Cyrl|=абвгдежзийклмнопрстуфхцчшщъьюя|BG|
mk|Macedonian|Македонски|Cyrl|=абвгдѓежзѕијклљмнњопрстќуфхцчџш|MK|
sr|Serbian (Cyrillic)|Српски|Cyrl Latn|=абвгдђежзијклљмнњопрстћуфхцчџш|RS BA ME|
rue|Rusyn|Русиньскый|Cyrl|ґєіїыў|SK UA|
el|Greek|Ελληνικά|Grek||GR CY|
# ---------------------------------------------------------------- Caucasus
hy|Armenian|Հայերեն|Armn||AM|
hyw|Western Armenian|Արեւմտահայերէն|Armn||LB SY TR|
ka|Georgian|ქართული|Geor||GE|
xmf|Mingrelian|მარგალური|Geor|ჷ|GE|
ab|Abkhaz|Аԥсуа|Cyrl|ҕҟҩԥҭҳҵҷҽҿәџ|GE|
os|Ossetian|Ирон|Cyrl|æ|RU GE|
ce|Chechen|Нохчийн|Cyrl|ӏ|RU|
av|Avar|Авар|Cyrl|ӏ|RU|
lez|Lezgian|Лезги|Cyrl|ӏ|RU AZ|
kbd|Kabardian|Адыгэбзэ|Cyrl|ӏ|RU|
# ---------------------------------------------------------------- Turkic / Mongolic (Cyrillic)
kk|Kazakh|Қазақша|Cyrl Latn|әғқңөұүһі|KZ|
ky|Kyrgyz|Кыргызча|Cyrl|ңөү|KG|
tt|Tatar|Татарча|Cyrl|әөүҗңһ|RU|
ba|Bashkir|Башҡортса|Cyrl|әөүғҡңҙҫһ|RU|
cv|Chuvash|Чӑвашла|Cyrl|ӑӗҫӳ|RU|
sah|Yakut (Sakha)|Саха тыла|Cyrl|ҕҥөһү|RU|
tyv|Tuvan|Тыва дыл|Cyrl|ңөү|RU|
uz-Cyrl|Uzbek (Cyrillic)|Ўзбекча|Cyrl|ўқғҳ|UZ|
tg|Tajik|Тоҷикӣ|Cyrl|ғӣқӯҳҷ|TJ|
mn|Mongolian|Монгол|Cyrl Mong|өү|MN|
mn-Mong|Mongolian (traditional script)|ᠮᠣᠩᠭᠣᠯ|Mong||CN MN|
bua|Buryat|Буряад|Cyrl|өүһ|RU|
xal|Kalmyk|Хальмг|Cyrl|әҗңөү|RU|
# ---------------------------------------------------------------- Middle East, Iran
ar|Arabic|العربية|Arab|ءآأؤإئة،؟ًٌٍَُِّْ|EG SA DZ MA IQ SD SY AE JO TN LB LY|
arz|Egyptian Arabic|مصرى|Arab|ءآأؤإئة|EG|
ary|Moroccan Arabic|الدارجة|Arab|ءآأؤإئةڤڭ|MA|
apc|Levantine Arabic|شامي|Arab|ءآأؤإئة|SY LB JO PS|
fa|Persian|فارسی|Arab|ءآأؤئپچژگکی،؟|IR|
prs|Dari|دری|Arab|ءآأؤئپچژگکی|AF|
ps|Pashto|پښتو|Arab|ټځڅډړږښګڼۍېيپچژگکی|AF PK|
ckb|Kurdish (Sorani)|کوردی|Arab|ڕڵۆێەڤپچژگکیھ|IQ IR|
ku|Kurdish (Kurmanji)|Kurmancî|Latn Arab Cyrl|çêîşû|TR SY IQ|
bal|Balochi|بلوچی|Arab|ٹڈپچژگکیےں|PK IR|
ur|Urdu|اردو|Arab|ٹڈڑںہھےۓپچژگکی|PK IN|Urdu is printed in Nastaliq style; at 20 px a Naskh font (Noto Naskh Arabic) stays legible, a Nastaliq font (Noto Nastaliq Urdu) is closer to print but cramped.
pa-Arab|Punjabi (Shahmukhi)|پنجابی|Arab|ٹڈڑںہھےپچژگکی|PK|
skr|Saraiki|سرائیکی|Arab|ٹڈڑںہھےٻڄڳݙپچگکی|PK|
sd|Sindhi|سنڌي|Arab Deva|ٻڀٽٿڄڃڇڊڌڍڏڙڦڪڳڱھپچگ۾ي|PK IN|
ks|Kashmiri|کٲشُر|Arab Deva|ٹڈڑںۄۆےٲپچژگکی|IN|
ug|Uyghur|ئۇيغۇرچە|Arab|ئەېۆۇۈۋڭگژپچھ|CN|
he|Hebrew|עברית|Hebr||IL|
yi|Yiddish|ייִדיש|Hebr|װױײַָּ|US IL|
syr|Syriac|ܣܘܪܝܝܐ|Syrc||SY IQ TR|
aii|Assyrian Neo-Aramaic|ܐܬܘܪܝܐ|Syrc||IQ IR SY|
dv|Dhivehi|ދިވެހި|Thaa||MV|
# ---------------------------------------------------------------- South Asia
hi|Hindi|हिन्दी|Deva||IN|
mr|Marathi|मराठी|Deva|ळ|IN|
ne|Nepali|नेपाली|Deva||NP IN|
sa|Sanskrit|संस्कृतम्|Deva|ॠऌॡॢॣ|IN|
kok|Konkani|कोंकणी|Deva|ळ|IN|
mai|Maithili|मैथिली|Deva||IN NP|
bho|Bhojpuri|भोजपुरी|Deva||IN NP|
awa|Awadhi|अवधी|Deva||IN|
mag|Magahi|मगही|Deva||IN|
hne|Chhattisgarhi|छत्तीसगढ़ी|Deva||IN|
raj|Rajasthani|राजस्थानी|Deva|ळ|IN|
mwr|Marwari|मारवाड़ी|Deva|ळ|IN|
doi|Dogri|डोगरी|Deva||IN|
brx|Bodo|बड़ो|Deva||IN|
new|Newari|नेपाल भाषा|Deva||NP|
gon|Gondi|गोंडी|Deva Telu||IN|
kru|Kurukh|कुँड़ुख़|Deva||IN|
sd-Deva|Sindhi (Devanagari)|सिन्धी|Deva|ॻॼॾॿ|IN|
ks-Deva|Kashmiri (Devanagari)|कॉशुर|Deva||IN|
bn|Bengali|বাংলা|Beng||BD IN|
as|Assamese|অসমীয়া|Beng|ৰৱ|IN|
syl|Sylheti|ꠍꠤꠟꠐꠤ|Sylo Beng||BD IN|
mni|Manipuri (Meitei)|মৈতৈলোন্|Beng Mtei||IN|
mni-Mtei|Manipuri (Meetei Mayek)|ꯃꯩꯇꯩꯂꯣꯟ|Mtei||IN|
ctg|Chittagonian|চাটগাঁইয়া|Beng||BD|
rhg|Rohingya|𐴌𐴗𐴥𐴝𐴙𐴚𐴒𐴙𐴝|Rohg Latn Arab||MM BD|
pa|Punjabi (Gurmukhi)|ਪੰਜਾਬੀ|Guru Arab||IN|
gu|Gujarati|ગુજરાતી|Gujr||IN|
or|Odia|ଓଡ଼ିଆ|Orya||IN|
ta|Tamil|தமிழ்|Taml||IN LK SG MY|
te|Telugu|తెలుగు|Telu||IN|
kn|Kannada|ಕನ್ನಡ|Knda||IN|
tcy|Tulu|ತುಳು|Knda||IN|
ml|Malayalam|മലയാളം|Mlym||IN|
si|Sinhala|සිංහල|Sinh||LK|
sat|Santali|ᱥᱟᱱᱛᱟᱲᱤ|Olck Beng Deva Latn||IN|
kha|Khasi|Ka Ktien Khasi|Latn|ïñ|IN|
lus|Mizo|Mizo ṭawng|Latn|âêîôûṭ|IN|
grt|Garo|A·chikku|Latn|·|IN BD|
lif|Limbu|ᤕᤠᤰᤌᤢᤱ|Limb Deva||NP IN|
ccp|Chakma|𑄌𑄋𑄴𑄟𑄳𑄦|Cakm||BD IN|
bo|Tibetan|བོད་སྐད་|Tibt||CN IN NP|
dz|Dzongkha|རྫོང་ཁ|Tibt||BT|
# ---------------------------------------------------------------- East Asia
zh-Hans|Chinese (Simplified)|简体中文|Hani|@zh-Hans|CN SG MY|
zh-Hant|Chinese (Traditional)|繁體中文|Hani|@zh-Hant|TW HK MO|
yue|Cantonese|粵語|Hani|@zh-Hant 冇嘅咗啲佢哋嘢|HK MO CN|Written Cantonese adds characters such as 嘅 咗 啲 佢 哋 冇 嘢 to Traditional Chinese.
wuu|Wu Chinese|吴语|Hani|@zh-Hans|CN|
nan|Min Nan (Hokkien)|閩南語|Hani Latn|@zh-Hant|TW CN SG|
nan-Latn|Hokkien (Pe̍h-ōe-jī)|Pe̍h-ōe-jī|Latn|áàâāa̍éèêēe̍íìîīi̍óòôōo̍o͘úùûūu̍ⁿ|TW|
hak|Hakka|客家話|Hani|@zh-Hant|TW CN|
ja|Japanese|日本語|Jpan|@ja|JP|
ain|Ainu|アイヌ イタㇰ|Kana Latn|=アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンㇰㇱㇲㇳㇴㇵㇶㇷㇸㇹㇺㇻㇼㇽㇾㇿ|JP|Ainu katakana uses the small kana ㇰ-ㇿ (U+31F0-31FF), which the retail font lacks.
ko|Korean|한국어|Hang Hani|@ko|KR KP|
ii|Yi (Nuosu)|ꆈꌠꉙ|Yiii||CN|
za|Zhuang|Vahcuengh|Latn||CN|
# ---------------------------------------------------------------- Southeast Asia
th|Thai|ไทย|Thai||TH|
lo|Lao|ລາວ|Laoo||LA|
km|Khmer|ខ្មែរ|Khmr||KH|
my|Burmese|မြန်မာ|Mymr||MM|
shn|Shan|လိၵ်ႈတႆး|Mymr|ၵၶၷၸၹၺၻၼၽၾၿႀႁႂႃႄႅႆႇႈႉႊ|MM|
ksw|S'gaw Karen|ကညီ|Mymr|ၡၢၤၥၦ|MM TH|
mnw|Mon|ဘာသာ မန်|Mymr|ၚၛၜၝၞၟၠ|MM TH|
nod|Northern Thai|ᨣᩴᩤᨾᩮᩬᩥᨦ|Lana Thai||TH|
blt|Tai Dam|ꪼꪕꪒꪾ|Tavt||VN|
vi|Vietnamese|Tiếng Việt|Latn|àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ|VN|
tl|Tagalog|Tagalog|Latn Tglg|ñ|PH|
fil|Filipino|Filipino|Latn|ñ|PH|
tl-Tglg|Tagalog (Baybayin)|ᜊᜌ᜔ᜊᜌᜒᜈ᜔|Tglg||PH|
ceb|Cebuano|Sinugboanon|Latn|ñ|PH|
ilo|Ilocano|Ilokano|Latn|ñ|PH|
hil|Hiligaynon|Ilonggo|Latn|ñ|PH|
war|Waray|Winaray|Latn|ñ|PH|
bik|Bikol|Bikol|Latn|ñ|PH|
pam|Kapampangan|Kapampangan|Latn|ñ|PH|
pag|Pangasinan|Pangasinan|Latn|ñ|PH|
ms|Malay|Bahasa Melayu|Latn Arab||MY BN SG|
ms-Arab|Malay (Jawi)|بهاس ملايو|Arab|ڠڤڽݢچ|MY BN|
id|Indonesian|Bahasa Indonesia|Latn||ID|
jv|Javanese|Basa Jawa|Latn Java|éè|ID|
jv-Java|Javanese (Aksara Jawa)|ꦧꦱꦗꦮ|Java||ID|
su|Sundanese|Basa Sunda|Latn Sund|é|ID|
su-Sund|Sundanese (Aksara Sunda)|ᮘᮞ ᮞᮥᮔ᮪ᮓ|Sund||ID|
mad|Madurese|Basa Madhura|Latn|âè|ID|
min|Minangkabau|Baso Minang|Latn||ID|
ban|Balinese|Basa Bali|Latn Bali|é|ID|
ban-Bali|Balinese (Aksara Bali)|ᬩᬲᬩᬮᬶ|Bali||ID|
bug|Buginese|Basa Ugi|Latn Bugi|é|ID|
bug-Bugi|Buginese (Lontara)|ᨅᨔ ᨕᨘᨁᨗ|Bugi||ID|
ace|Acehnese|Bahsa Acèh|Latn|èéëô|ID|
bjn|Banjar|Bahasa Banjar|Latn||ID|
tet|Tetum|Tetun|Latn|ñ|TL|
hmn|Hmong (RPA)|Hmoob|Latn||LA US VN TH CN|
hnj|Hmong (Nyiakeng Puachue)|𞄀𞄩𞄰|Hmnp||US LA|
# ---------------------------------------------------------------- Africa: Horn, Sahel, Maghreb
am|Amharic|አማርኛ|Ethi||ET|
ti|Tigrinya|ትግርኛ|Ethi||ER ET|
tig|Tigre|ትግረ|Ethi||ER|
gez|Ge'ez|ግዕዝ|Ethi||ET ER|Liturgical.
om|Oromo|Afaan Oromoo|Latn|ʼ|ET KE|
so|Somali|Soomaali|Latn Osma Arab||SO ET DJ KE|
so-Osma|Somali (Osmanya)|𐒈𐒝𐒑𐒛𐒐𐒘|Osma||SO|
aa|Afar|Qafaraf|Latn||ET ER DJ|
sid|Sidamo|Sidaamu Afoo|Latn||ET|
wal|Wolaytta|Wolaytta|Latn||ET|
zgh|Tamazight (Standard Moroccan)|ⵜⴰⵎⴰⵣⵉⵖⵜ|Tfng||MA|
shi|Tachelhit|ⵜⴰⵛⵍⵃⵉⵜ|Tfng Latn Arab||MA|
tzm|Central Atlas Tamazight|ⵜⴰⵎⴰⵣⵉⵖⵜ|Tfng Latn||MA|
kab|Kabyle|Taqbaylit|Latn Tfng|čḍǧḥɛɣṛṣṭẓ|DZ|
rif|Tarifit|Tarifit|Latn Tfng Arab|čḍǧḥɛɣṛṣṭẓ|MA|
taq|Tamasheq|Tamasheq|Latn Tfng|ăǝḍɣšṭẓ|ML NE BF|
ha|Hausa|Hausa|Latn Arab|ɓɗƙƴʼ|NG NE GH|
ha-Arab|Hausa (Ajami)|هَوُسَ|Arab|ٻڟٿۏ|NG NE|
kr|Kanuri|Kanuri|Latn|ǝ|NG NE TD|
dje|Zarma|Zarmaciine|Latn|ãéɲŋšž|NE|
son|Songhay|Soŋay|Latn|ɲŋšž|ML|
ff|Fula|Fulfulde|Latn Adlm|ɓɗŋɲƴ|SN GN ML NG CM NE|
ff-Adlm|Fula (Adlam)|𞤊𞤵𞤤𞤬𞤵𞤤𞤣𞤫|Adlm||GN SN|
wo|Wolof|Wolof|Latn Arab|àéëñóŋ|SN GM|
mnk|Mandinka|Mandinka|Latn Nkoo Arab|ñŋ|GM SN GW|
bm|Bambara|Bamanankan|Latn Nkoo|ɛɔɲŋ|ML|
bm-Nkoo|Bambara (N'Ko)|ߓߡߊߣߊ߲ߞߊ߲|Nkoo||ML|
nqo|N'Ko (Manding)|ߒߞߏ|Nkoo||GN ML CI|
dyu|Dyula|Julakan|Latn Nkoo|ɛɔɲŋ|CI BF|
emk|Maninka|Maninkakan|Latn Nkoo|ɛɔɲŋ|GN|
vai|Vai|ꕙꔤ|Vaii Latn||LR SL|
kpe|Kpelle|Kpɛlɛɛ|Latn|ɛɔŋ|LR GN|
men|Mende|Mɛnde|Latn|ɛɔŋ|SL|
tem|Temne|KʌThemnɛ|Latn|ɛɔʌŋ|SL|
mos|Mossi (Mooré)|Mòoré|Latn|ɛɩʋãẽĩõũ|BF|
dag|Dagbani|Dagbanli|Latn|ɛɣŋɔʒ|GH|
tw|Twi (Akan)|Twi|Latn|ɛɔ|GH|
ak|Akan|Akan|Latn|ɛɔ|GH|
ee|Ewe|Eʋegbe|Latn|ɖɛƒɣŋɔʋ|GH TG|
fon|Fon|Fɔngbè|Latn|ɖɛɔàáèéìíòóùú|BJ|
gaa|Ga|Gã|Latn|ɛɔŋ|GH|
# ---------------------------------------------------------------- Africa: West/Central (Nigeria, Cameroon, Congo)
yo|Yoruba|Yorùbá|Latn|àáèéẹ̀ẹ́ẹìíòóọ̀ọ́ọùúṣńḿ|NG BJ|Tone marks on ẹ and ọ are a dot below plus a combining accent; each letter with its marks is one glyph.
ig|Igbo|Asụsụ Igbo|Latn|ịọụṅ|NG|
efi|Efik|Usem Efịk|Latn|ịọ|NG|
ibb|Ibibio|Ibibio|Latn|ʌ|NG|
tiv|Tiv|Tiv|Latn||NG|
bin|Edo|Ẹ̀dó|Latn|ẹọ|NG|
urh|Urhobo|Urhobo|Latn|ẹọ|NG|
ijc|Izon|Ịjọ|Latn|ẹịọụ|NG|
nup|Nupe|Nupe|Latn||NG|
pcm|Nigerian Pidgin|Naijá|Latn|ẹọ|NG|
bmo|Bambalang|Bambalang|Latn|ɛɔŋ|CM|
bax|Bamum|ꚶꚤꚳ|Bamu Latn||CM|
ewo|Ewondo|Ewondo|Latn|ɛəɔŋ|CM|
dua|Duala|Duálá|Latn|ɓɛŋɔ|CM|
sg|Sango|Sängö|Latn|âäêëîïôöûü|CF|
ln|Lingala|Lingála|Latn|ɛɔáéíóú|CD CG|
kg|Kikongo|Kikongo|Latn||CD CG AO|
lua|Tshiluba|Tshiluba|Latn||CD|
rw|Kinyarwanda|Ikinyarwanda|Latn||RW|
rn|Kirundi|Ikirundi|Latn||BI|
# ---------------------------------------------------------------- Africa: East
sw|Swahili|Kiswahili|Latn||TZ KE UG CD|
lg|Luganda|Luganda|Latn|ŋ|UG|
luo|Luo (Dholuo)|Dholuo|Latn||KE TZ|
kln|Kalenjin|Kalenjin|Latn||KE|
ki|Kikuyu|Gĩkũyũ|Latn|ĩũ|KE|
kam|Kamba|Kikamba|Latn|ĩũ|KE|
guz|Gusii|Ekegusii|Latn||KE|
mer|Meru|Kĩmĩrũ|Latn|ĩũ|KE|
suk|Sukuma|Kɪsukuma|Latn||TZ|
nyn|Nyankole|Runyankore|Latn||UG|
xog|Soga|Lusoga|Latn|ŋ|UG|
din|Dinka|Thuɔŋjäŋ|Latn|äëɛɣïŋöɔ|SS|
nus|Nuer|Thok Naath|Latn|äëɛɣïŋöɔ|SS ET|
# ---------------------------------------------------------------- Africa: Southern
zu|Zulu|isiZulu|Latn||ZA|
xh|Xhosa|isiXhosa|Latn||ZA|
ss|Swati|siSwati|Latn||SZ ZA|
nr|Southern Ndebele|isiNdebele|Latn||ZA|
nd|Northern Ndebele|isiNdebele|Latn||ZW|
st|Sesotho|Sesotho|Latn||LS ZA|
nso|Sepedi|Sesotho sa Leboa|Latn|êôš|ZA|
tn|Setswana|Setswana|Latn|êôš|BW ZA|
ts|Tsonga|Xitsonga|Latn||ZA MZ|
ve|Venda|Tshivenḓa|Latn|ḓḽṅṋṱ|ZA|
af|Afrikaans|Afrikaans|Latn|êëéèîïôû|ZA NA|
sn|Shona|chiShona|Latn||ZW|
ny|Chichewa|Chichewa|Latn|ŵ|MW ZM MZ|
bem|Bemba|Ichibemba|Latn||ZM|
toi|Tonga (Zambia)|Chitonga|Latn||ZM ZW|
loz|Lozi|Silozi|Latn||ZM|
vmw|Makhuwa|Emakhuwa|Latn||MZ|
seh|Sena|Cisena|Latn||MZ|
yao|Yao|Chiyao|Latn|ŵ|MW MZ TZ|
umb|Umbundu|Umbundu|Latn||AO|
kmb|Kimbundu|Kimbundu|Latn||AO|
hz|Herero|Otjiherero|Latn||NA|
ng|Ndonga|Oshindonga|Latn||NA|
kj|Kwanyama|Oshikwanyama|Latn||NA AO|
naq|Khoekhoe|Khoekhoegowab|Latn|ǀǁǂǃâîû|NA|The clicks are written ǀ ǁ ǂ ǃ (U+01C0-01C3), not | or !.
mg|Malagasy|Malagasy|Latn|ô|MG|
# ---------------------------------------------------------------- Americas: Indigenous
chr|Cherokee|ᏣᎳᎩ|Cher|ᏣᎳᎩ|US|Syllabary letters U+13A0-13F4 (the forms most fonts and keyboards produce). Plantagenet Cherokee ships with macOS; Noto Sans Cherokee is free.
iu|Inuktitut|ᐃᓄᒃᑎᑐᑦ|Cans Latn|@iu|CA|Syllabics (qaniujaaqpait); Inuinnaqtun and Labrador Inuttut use Latin letters (iu-Latn).
iu-Latn|Inuktitut (Latin)|Inuktitut|Latn|ł|CA|
ikt|Inuinnaqtun|Inuinnaqtun|Latn|ł|CA|
cr|Cree (syllabics)|ᓀᐦᐃᔭᐍᐏᐣ|Cans Latn|@cr|CA|Plains and Swampy Cree syllabics; long vowels carry a dot above.
cr-Latn|Cree (Latin)|nēhiyawēwin|Latn|âêîôāēīō|CA|Standard Roman Orthography (Plains Cree): long vowels with a circumflex or a macron.
oj|Ojibwe|Anishinaabemowin|Latn Cans||CA US|Double-vowel (Fiero) orthography: ASCII letters and the glottal stop ʼ or '.
oj-Cans|Ojibwe (syllabics)|ᐊᓂᔑᓈᐯᒧᐎᓐ|Cans|@oj|CA|
oji-Latn|Oji-Cree|Anishininiimowin|Latn Cans||CA|
bla|Blackfoot|Siksiká|Latn Cans|áíó|CA US|
nv|Navajo|Diné bizaad|Latn|áéíóąęįǫą́ę́į́ǫ́łńʼ|US|Nasal vowels with ogonek (ą ę į ǫ), high tone with an acute (both on one vowel = one glyph), ł, and the glottal stop ʼ (U+02BC).
lkt|Lakota|Lakȟótiyapi|Latn|áéíóúąįųčǧȟšžŋʼ|US|
dak|Dakota|Dakȟótiyapi|Latn|áéíóúąįųčǧȟšžŋʼ|US CA|
moh|Mohawk|Kanienʼkéha|Latn|áéóʼ|CA US|
cho|Choctaw|Chahta|Latn|ạịọ|US|
mus|Muscogee|Mvskoke|Latn||US|
hop|Hopi|Hopìikwa|Latn|àèìòùö|US|
tli|Tlingit|Lingít|Latn|áéíóúx̱ḵ|US CA|
esu|Central Yupik|Yugtun|Latn|ḡńḿ|US|
ik|Iñupiaq|Iñupiatun|Latn|ġḷłŋñ|US|
kl|Greenlandic|Kalaallisut|Latn|æøå|GL|
ht|Haitian Creole|Kreyòl ayisyen|Latn|èò|HT|
pap|Papiamento|Papiamentu|Latn|áéíóúèòùñü|CW AW BQ|
qu|Quechua|Runa Simi|Latn|ñ|PE BO EC|Southern Quechua orthography; ejectives and aspirates are written with ' and h.
ay|Aymara|Aymar aru|Latn|äïüñ|BO PE|
gn|Guarani|Avañeʼẽ|Latn|ãẽĩõũỹg̃ñáéíóúýʼ|PY BO|The nasal g̃ is g + combining tilde; the puso (glottal stop) is ʼ (U+02BC).
nah|Nahuatl|Nāhuatlahtōlli|Latn|āēīō|MX|Macrons mark long vowels in academic spelling; many communities write without them.
nhe|Eastern Huasteca Nahuatl|Nahuatl|Latn||MX|
yua|Yucatec Maya|Maaya tʼaan|Latn|ʼ|MX BZ|
quc|K'iche'|Kʼicheʼ|Latn|ʼ|GT|
kek|Q'eqchi'|Qʼeqchiʼ|Latn|ʼ|GT BZ|
cak|Kaqchikel|Kaqchikel|Latn|äëïöüʼ|GT|
mam|Mam|Qyolj|Latn|ʼ|GT MX|
mix|Mixtec|Tu'un savi|Latn|ɨ|MX|
zap|Zapotec|Diidxazá|Latn|áéíóú|MX|
oto|Otomi|Hñähñu|Latn|äëɨöüñ|MX|
arn|Mapudungun|Mapudungun|Latn|üñ|CL AR|
guc|Wayuu|Wayuunaiki|Latn|ü|CO VE|
shp|Shipibo|Shipibo|Latn||PE|
cni|Asháninka|Asháninka|Latn||PE|
# ---------------------------------------------------------------- Pacific
haw|Hawaiian|ʻŌlelo Hawaiʻi|Latn|āēīōūʻ|US|The ʻokina is U+02BB (not an apostrophe); the kahakō is a macron.
mi|Māori|Te reo Māori|Latn|āēīōū|NZ|
sm|Samoan|Gagana Sāmoa|Latn|āēīōūʻ|WS AS|
to|Tongan|Lea faka-Tonga|Latn|āēīōūʻ|TO|
ty|Tahitian|Reo Tahiti|Latn|āēīōūʻ|PF|
fj|Fijian|Na Vosa Vakaviti|Latn||FJ|
ch|Chamorro|Finuʼ Chamoru|Latn|åñʼ|GU MP|
mh|Marshallese|Kajin M̧ajeļ|Latn|āļm̧ņn̄o̧ōū|MH|
gil|Gilbertese|Taetae ni Kiribati|Latn||KI|
pau|Palauan|Tekoi er a Belau|Latn||PW|
tpi|Tok Pisin|Tok Pisin|Latn||PG|
bi|Bislama|Bislama|Latn||VU|
ho|Hiri Motu|Hiri Motu|Latn||PG|
wbp|Warlpiri|Warlpiri|Latn||AU|
pjt|Pitjantjatjara|Pitjantjatjara|Latn|ḻṉṟṯ|AU|
aer|Eastern Arrernte|Arrernte|Latn||AU|
djr|Djambarrpuyngu (Yolŋu Matha)|Yolŋu Matha|Latn|äŋḏḻṉṯ|AU|
"""

# Canadian syllabics repertoires, built from Unicode character names
# (``CANADIAN SYLLABICS <consonant><vowel>``) so no code point is typed by
# hand: consonants, vowels and the finals each orthography uses.
CANS_SETS = {
    # Nunavut Inuktitut: i/ii/u/uu/a/aa series + finals
    "iu": {"consonants": ["", "P", "T", "K", "G", "M", "N", "S", "L", "Y", "V", "R", "Q", "NG", "LH"],
           "vowels": ["I", "II", "U", "UU", "A", "AA"],
           "finals": ["P", "T", "K", "G", "M", "N", "S", "L", "Y", "V", "R", "Q", "NG", "LH", "H"]},
    # Plains Cree (western): e/i/ii/o/oo/a/aa series + finals
    "cr": {"consonants": ["", "W", "P", "T", "K", "C", "M", "N", "S", "Y"],
           "vowels": ["E", "I", "II", "O", "OO", "A", "AA"],
           "finals": ["P", "T", "K", "C", "M", "N", "S", "Y", "W", "H"]},
    # Ojibwe (eastern syllabics): e/i/ii/o/oo/a/aa series + finals
    "oj": {"consonants": ["", "W", "P", "T", "K", "C", "M", "N", "S", "SH", "Y"],
           "vowels": ["E", "I", "II", "O", "OO", "A", "AA"],
           "finals": ["P", "T", "K", "C", "M", "N", "S", "SH", "Y", "W", "H"]},
}

# Sample sentences shown in the editor (and used by txtarget's selftest)
SAMPLES = {
    "fr": "Portez ce vieux whisky au juge blond qui fume. « Où est KOS-MOS ? »",
    "es": "El veloz murciélago hindú comía feliz cardillo y kiwi. ¿Dónde está?",
    "de": "Victor jagt zwölf Boxkämpfer quer über den großen Sylter Deich.",
    "it": "Ma la volpe col suo balzo ha raggiunto il quieto Fido. Perché è così?",
    "pt": "Luís argüia à Júlia que «brações, fé, chá, óxido, pôr, zângão» eram palavras.",
    "pt-BR": "À noite, vovô Kowalsky vê o ímã cair no pé do pinguim.",
    "nl": "Pa's wijze lynx bezag vroom het fikse aquaduct. Één, twee, drieëntwintig.",
    "ca": "Jove xef, porti whisky amb quinze glaçons d'hidrogen, coi! Col·lega.",
    "sv": "Flygande bäckasiner söka hwila på mjuka tuvor.",
    "da": "Høj bly gom vandt fræk sexquiz på wc.",
    "no": "Vår sære Zulu fra badeøya spilte jo whist og quickstep i min taxi.",
    "fi": "Törkylempijävongahdus. Šakki ja žirafi.",
    "is": "Kæmi ný öxi hér, ykist þjófum nú bæði víl og ádrepa.",
    "ga": "D'fhuascail Íosa Úrmhac na hÓighe Beannaithe pór Éava agus Ádhaimh.",
    "af": "Sê vir die mense: môre is ’n nuwe dag.",
    "sq": "Unë jam KOS-MOS. Çfarë dëshironi?",
    "id": "Saya KOS-MOS. Apa yang bisa saya bantu?",
    "eo": "Eĥoŝanĝo ĉiuĵaŭde. Laŭ Ludoviko Zamenhof bongustas freŝa ĉeĥa manĝaĵo.",
    "pl": "Zażółć gęślą jaźń. Pchnąć w tę łódź jeża lub ośm skrzyń fig.",
    "cs": "Příliš žluťoučký kůň úpěl ďábelské ódy.",
    "sk": "Kŕdeľ šťastných ďatľov učí pri ústí Váhu mĺkveho koňa obhrýzať kôru.",
    "sl": "Hišničin bratec vzgaja polžke še čez zimo.",
    "hr": "Gojazni đačić s biciklom drži hmelj i finu vatu u džepu nošnje.",
    "hu": "Árvíztűrő tükörfúrógép.",
    "ro": "Înjurând pițigăiat, zoofobul comandă vexat whisky și tequila.",
    "tr": "Pijamalı hasta yağız şoföre çabucak güvendi.",
    "et": "Põdur Zagrebi tšellomängija-följetonist Ciqo külmetas kehvas garaažis.",
    "lt": "Įlinkdama fechtuotojo špaga sublykčiojusi pragręžė apvalų arbūzą.",
    "lv": "Glāžšķūņa rūķīši dzērumā čiepj Baha koncertflīģeļu vākus.",
    "vi": "Tôi là KOS-MOS. Bạn cần giúp gì không?",
    "ja": "こんにちは、シオン。漢字と仮名、そして叡智。",
    "ru": "Съешь же ещё этих мягких французских булок, да выпей чаю.",
    "uk": "Чуєш їх, доцю, га? Кумедна ж ти, прощайся без ґольфів!",
    "bg": "Жълтата дюля беше щастлива, че пухът, който цъфна, замръзна като гьон.",
    "sr": "Фијуче ветар у шибљу, леди пасаже и куће иза њих и гунђа у оџацима.",
    "el": "Ξεσκεπάζω την ψυχοφθόρα βδελυγμία.",
    "hy": "Բարեւ, աշխարհ։",
    "ka": "გამარჯობა, სამყარო!",
    "ar": "مرحبا بالعالم! أنا KOS-MOS (3).",
    "fa": "سلام دنیا! من KOS-MOS هستم.",
    "he": "שלום עולם! אני KOS-MOS.",
    "hi": "नमस्ते दुनिया! मैं KOS-MOS हूँ।",
    "th": "สวัสดีชาวโลก",
    "am": "ሰላም ዓለም።",
    "ko": "안녕하세요, 세계! 저는 KOS-MOS입니다.",
    "zh-Hans": "你好，世界！我是KOS-MOS。",
    "zh-Hant": "你好，世界！我是KOS-MOS。",
    "chr": "ᎣᏏᏲ! ᎪᏍᎹᏍ ᏓᏆᏙᎥ.",
    "haw": "Aloha! ʻO KOS-MOS koʻu inoa.",
    "mi": "Kia ora! Ko KOS-MOS tōku ingoa.",
    "nv": "Yáʼátʼééh! KOS-MOS yinishyé.",
    "sw": "Habari! Mimi ni KOS-MOS.",
    "yo": "Ẹ kú àárọ̀! Orúkọ mi ni KOS-MOS.",
}
