"""The competitor record: what each register can and cannot say, kept apart."""

import datetime as dt
import pathlib

import db
import competitors as C
from fetchers import exclusivity_purplebook as PB

BACKEND = pathlib.Path(__file__).resolve().parent.parent
TODAY = dt.date(2026, 11, 17)

HEADER = ("N/R/U,Applicant,BLA Number,Proprietary Name,Proper Name,License Type,Strength,"
          "Dosage Form,Route of Administration,Product Presentation,Marketing Status,"
          "Licensure,Approval Date,Inter. Approval Date,Ref. Product Proper Name,"
          "Ref. Product Proprietary Name\n")
PURPLE = ("Purple Book Monthly Historical Data Changes Report,,,\n,,,\n" + HEADER + "\n".join([
    ',"Sandoz Inc.",761042,Erelzi,etanercept-szzs,351(k) Biosimilar,50MG,Injection,Sub,'
    'Pre-Filled Syringe,Disc,Licensed,"August 30, 2016",,etanercept,Enbrel',
    ',"Sandoz Inc.",761042,Erelzi,etanercept-szzs,351(k) Biosimilar,25MG,Injection,Sub,'
    'Pre-Filled Syringe,Disc,Licensed,"November 10, 2022",,etanercept,Enbrel',
    ',Amgen Inc.,761024,Amjevita,adalimumab-atto,351(k) Biosimilar,40MG,Injection,Sub,'
    'Pen,Disc,Licensed,"September 23, 2016",,adalimumab,Humira',
    ',Amgen Inc.,761024,Amjevita,adalimumab-atto,351(k) Interchangeable,40MG,Injection,'
    'Sub,Syringe,Rx,Licensed,"April 6, 2023","April 6, 2023",adalimumab,Humira',
    ',AbbVie Inc.,125057,Humira,adalimumab,351(a),40MG,Injection,Sub,Pen,Rx,Licensed,'
    '"December 31, 2002",,,',
]) + "\n")


def test_a_biosimilar_is_one_row_a_brand_with_its_first_approval_and_whether_any_is_listed():
    rows = {r["proprietary_name"]: r for r in PB.parse_biosimilars(PURPLE)}
    assert set(rows) == {"Erelzi", "Amjevita"}                 # the reference is not one
    assert rows["Erelzi"]["approval_date"] == "2016-08-30"
    assert rows["Erelzi"]["marketing_status"] == "Disc"        # every presentation is
    assert rows["Erelzi"]["reference_proprietary"] == "Enbrel"
    assert rows["Amjevita"]["marketing_status"] == "Rx"        # one still is
    assert rows["Amjevita"]["approval_date"] == "2016-09-23"
    assert "Interchangeable" in rows["Amjevita"]["licence_type"]
    assert PB.parse_biosimilars("no header here") == []


def test_a_brand_with_its_device_is_the_reference_and_a_longer_brand_is_not():
    assert C.is_reference("Lantus Solostar", "Lantus")
    assert C.is_reference("Simponi Simponi Aria", "Simponi Aria")   # one reported line
    assert C.is_reference("Simponi Aria", "Simponi Aria")
    assert C.is_reference("HUMIRA", "Humira")
    assert not C.is_reference("Eylea Hd", "Eylea")     # its own licence, nothing copies it
    assert not C.is_reference("Prolia", "Xgeva")
    assert not C.is_reference(None, "Humira") and not C.is_reference("Humira", "")


def _lic(reference, name, status="Rx", approved="2023-01-01"):
    return {"reference_proprietary": reference, "proprietary_name": name,
            "marketing_status": status, "approval_date": approved}


def test_each_register_says_its_own_thing():
    bio = {"id": 1, "brand_name": "Humira", "modality": "biologic", "internal_code": "BLA1"}
    small = {"id": 2, "brand_name": "Crestor", "modality": "small molecule",
             "internal_code": "N021366"}
    licences = {"Humira": [_lic("Humira", "Amjevita"), _lic("Humira", "Hadlima", "Disc")],
                "Enbrel": [_lic("Enbrel", "Erelzi", "Disc")]}
    # a generic launch on the Paragraph IV list is a launch
    got = C.for_asset(small, "2016-05-02", {}, [])
    assert (got["status"], got["kind"], got["since"]) == (C.ON_MARKET, "generic", "2016-05-02")
    # a licence still listed is not a launch
    got = C.for_asset(bio, None, licences, [])
    assert (got["status"], got["licensed"], got["listed"]) == (C.LICENSED, 2, 1)
    assert "2 biosimilar licences, 1 still listed" in got["evidence"][0]["says"]
    # until the filer says so
    said = [{"market": "US", "kind": "biosimilar", "status": C.ON_MARKET, "launched": "2023-01",
             "source": "10-K 0001551152-26-000008", "quote": "biosimilars entered the U.S."}]
    got = C.for_asset(bio, None, licences, said)
    assert (got["status"], got["kind"], got["since"]) == (C.ON_MARKET, "biosimilar", "2023-01")
    # licensed and every presentation discontinued
    enbrel = {"id": 3, "brand_name": "Enbrel", "modality": "biologic"}
    assert C.for_asset(enbrel, None, licences, [])["status"] == C.SHELVED
    # a biologic with no licence against it, and a small molecule the list is silent on
    botox = {"id": 4, "brand_name": "Botox", "modality": "biologic"}
    assert C.for_asset(botox, None, licences, [])["status"] == C.NONE_LICENSED
    zoladex = {"id": 5, "brand_name": "Zoladex", "modality": "small molecule"}
    assert C.for_asset(zoladex, None, licences, [])["status"] == C.NONE_RECORDED
    # licensed and listed, and the owner says none has launched
    says_no = [{"market": "US", "kind": "biosimilar", "status": "none", "launched": None,
                "source": "10-Q", "quote": "a potential U.S. entrant later in 2026"}]
    assert C.for_asset(bio, None, licences, says_no)["status"] == C.NOT_LAUNCHED
    assert C.for_asset(botox, None, licences, says_no)["status"] == C.NONE_LICENSED
    # a launch abroad is recorded and is not a US launch
    abroad = [{"market": "EU", "kind": "biosimilar", "status": C.ON_MARKET, "launched": "2018",
               "source": "20-F", "quote": ""}]
    got = C.for_asset(botox, None, licences, abroad)
    assert got["status"] == C.NONE_LICENSED and got["elsewhere"] == ["EU"]


def test_a_filers_date_counts_once_it_has_passed_and_a_settled_date_ahead_does_not(tmp_path):
    disclosed = tmp_path / "disclosed.csv"
    disclosed.write_text(
        "ticker,brand,loe,basis,note\n"
        'BIIB,Tecfidera,expired,"Biogen 10-K, U.S. generic entry","generic entrants are in"\n'
        'ROG,Rituxan,2019,"Roche Finance Report 2025, first US biosimilar","note"\n'
        'REGN,Eylea,2027,"Regeneron 10-Qs, settled U.S. biosimilar entry","settlements"\n'
        'ROG,Perjeta,2026,"Roche Finance Report 2025, first US biosimilar","anticipated"\n'
        'ROG,Xolair,2025,"Roche Finance Report 2025, anticipated first US biosimilar",""\n'
        'AZN,Soliris,2025-03-01,"AstraZeneca 20-F, settled biosimilar entry",""\n'
        'PFE,Xeljanz,2026,"Pfizer 10-K, U.S. basic product patent",""\n')
    launches = tmp_path / "launches.csv"
    launches.write_text(
        "ticker,product,market,kind,status,launched,accession,form,filed,quote,note\n"
        "ABBV,Humira,US,biosimilar,on the market,2023-01,0001551152-26-000008,10-K,"
        '2026-02-20,"direct biosimilar competition in the U.S. began",\n')
    said = C.stated(launches, disclosed, TODAY)
    assert said[("BIIB", ("tecfidera",))][0]["kind"] == "generic"
    assert said[("ROG", ("rituxan",))][0]["launched"] == "2019"
    assert ("REGN", ("eylea",)) not in said             # coming, not here
    assert ("ROG", ("perjeta",)) not in said            # this year is not over
    assert ("ROG", ("xolair",)) not in said             # anticipated, even once passed
    assert ("AZN", ("soliris",)) not in said            # a settlement date is a permission
    assert ("PFE", ("xeljanz",)) not in said            # a patent date names no competitor
    humira = said[("ABBV", ("humira",))][0]
    assert humira["source"] == "10-K 0001551152-26-000008" and humira["launched"] == "2023-01"


def test_the_record_reads_every_marketed_product_from_the_three_registers(tmp_path):
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'ABBV', 'AbbVie')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, modality,"
                 " is_marketed, internal_code) VALUES (1, 1, 'Humira', 'biologic', 1, 'BLA125057'),"
                 " (2, 1, 'Botox', 'biologic', 1, 'BLA103000'),"
                 " (3, 1, 'Pipeline thing', 'biologic', 0, 'ABBV-1')")
    PB.write_biosimilars(conn, PB.parse_biosimilars(PURPLE))
    conn.commit()
    empty = tmp_path / "none.csv"
    empty.write_text("ticker,brand,loe,basis,note\n")
    rows = {r["name"]: r for r in C.record(conn, "ABBV", launches=empty, disclosed=empty,
                                           today=TODAY)}
    conn.close()
    assert set(rows) == {"Humira", "Botox"}             # marketed products only
    assert rows["Humira"]["status"] == C.LICENSED and rows["Humira"]["licensed"] == 1
    assert rows["Botox"]["status"] == C.NONE_LICENSED


def test_the_curated_launches_each_cite_a_filing_and_quote_it():
    for row in C._rows(C.LAUNCHES):
        assert row["ticker"] and row["product"] and row["market"], row
        assert row["status"] in ("on the market", "licensed, not launched", "none"), row
        # an SEC filing by its accession; Roche, which files none, by the report's name
        assert row["form"] and (row["accession"] or row["ticker"] == "ROG"), row
        assert row["quote"].strip(), row
    assert len(C._rows(C.LAUNCHES)) >= 40


def test_the_record_is_a_view_beside_the_value():
    for name in ("forecast", "assumptions", "forecast_view", "company_score", "breakpoints",
                 "fair_value", "loe"):
        assert "import competitors" not in (BACKEND / f"{name}.py").read_text(), name
