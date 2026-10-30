# Source material for data/iucn-guidelines/current

The official IUCN Red List PDFs and the `parse_pdf.py` extraction script
used to produce the markdown in `../current/*/*.md` (byte-identical to
the `.md` output here at the time of extraction).

```
source/
├── parse_pdf.py                              # PDF -> markdown/images/source-map extraction script
├── user-guidelines/
│   ├── user-guidelines-v16.pdf                # Original source PDF
│   ├── user-guidelines-v16-source-map.json    # Section headers -> page/bbox coordinates
│   └── images/                                # Extracted diagrams and flowcharts
├── categories-and-criteria/
├── supporting-info/
├── mapping-standards/
└── regional-guidelines/
```

## Re-extracting

```bash
cd data/iucn-guidelines/source
python3 parse_pdf.py <pdf_file> <output_dir>
```

Writes/updates a markdown file (named to match the PDF, e.g.
`user-guidelines-v16.md`) with page markers, markdown tables, and image
references, plus a `<name>-source-map.json`.

## Citation

- IUCN. 2012. *IUCN Red List Categories and Criteria: Version 3.1.* Second edition. Gland, Switzerland and Cambridge, UK: IUCN.
- IUCN Standards and Petitions Committee. 2024. *Guidelines for Using the IUCN Red List Categories and Criteria.* Version 16.
- IUCN. 2012. *Guidelines for Application of IUCN Red List Criteria at Regional and National Levels: Version 4.0.* Gland, Switzerland and Cambridge, UK: IUCN.

These are official IUCN publications.
