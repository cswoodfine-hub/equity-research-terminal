

def test_patent_kind_reads_the_books_flags():
    from fetchers.exclusivity_orangebook import patent_kind
    # Substance outranks the rest: a patent claiming the molecule blocks a generic
    # whatever else it claims.
    assert patent_kind({"substance": True, "product": True, "use": True}) == "substance"
    assert patent_kind({"substance": False, "product": True, "use": True}) == "product"
    assert patent_kind({"substance": False, "product": False, "use": True}) == "use"
    assert patent_kind({"substance": False, "product": False, "use": False}) is None
    assert patent_kind(None) is None
