// ================================================================
// LegalRAG — Neo4j Schema
// Chạy một lần khi khởi tạo database
// ================================================================

// === CONSTRAINTS ===

CREATE CONSTRAINT doc_number_unique IF NOT EXISTS
FOR (d:Document) REQUIRE d.doc_number IS UNIQUE;

CREATE CONSTRAINT org_name_unique IF NOT EXISTS
FOR (o:Organization) REQUIRE o.name IS UNIQUE;

// === INDEXES ===

CREATE INDEX doc_status IF NOT EXISTS
FOR (d:Document) ON (d.status);

CREATE INDEX doc_type_idx IF NOT EXISTS
FOR (d:Document) ON (d.doc_type);

CREATE INDEX doc_issue_date IF NOT EXISTS
FOR (d:Document) ON (d.issue_date);

CREATE FULLTEXT INDEX doc_title_search IF NOT EXISTS
FOR (d:Document) ON EACH [d.title, d.doc_number];

// ================================================================
// Ví dụ tạo dữ liệu mẫu (uncomment để test)
// ================================================================

/*
CREATE (d:Document {
  doc_number:     "13/2023/NĐ-CP",
  doc_type:       "Nghị định",
  title:          "Nghị định về bảo vệ dữ liệu cá nhân",
  issuer:         "Chính phủ",
  issue_date:     "2023-04-17",
  effective_date: "2023-07-01",
  status:         "HIEU_LUC",
  legal_domain:   ["công nghệ thông tin", "bảo vệ dữ liệu cá nhân"]
});

CREATE (d2:Document {
  doc_number:     "Luật An toàn thông tin mạng 2015",
  doc_type:       "Luật",
  title:          "Luật An toàn thông tin mạng",
  issuer:         "Quốc hội",
  issue_date:     "2015-11-19",
  effective_date: "2016-07-01",
  status:         "HIEU_LUC",
  legal_domain:   ["công nghệ thông tin", "an toàn thông tin"]
});

MATCH (nd:Document {doc_number: "13/2023/NĐ-CP"})
MATCH (luat:Document {doc_number: "Luật An toàn thông tin mạng 2015"})
MERGE (nd)-[:CAN_CU {
  specific_articles: ["Điều 46", "Điều 47"],
  confidence: 0.95
}]->(luat);
*/
