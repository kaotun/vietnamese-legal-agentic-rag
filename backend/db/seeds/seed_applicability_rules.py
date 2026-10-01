"""Script nạp và đồng bộ danh mục quy tắc pháp lý mở rộng (Legal Applicability Rules) vào PostgreSQL."""
import json
import logging
from psycopg2.extras import execute_values
from src.core.database import get_db_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RULES_DATA = [
    (
        "RULE_CRIMINAL_MIN_AGE_14",
        "Độ tuổi tối thiểu chịu trách nhiệm hình sự (Điều 12 BLHS 2015)",
        "criminal",
        "BLHS_2015",
        "Điều 12",
        json.dumps({
            "domain": "criminal",
            "facts": {
                "age": {"operator": "<", "value": 14}
            },
            "blocked_intents": ["punishment", "imprisonment", "criminal_prosecution", "prison_years"]
        }, ensure_ascii=False),
        "BLOCK",
        json.dumps({
            "applicable": False,
            "reason": "age_below_criminal_liability_threshold",
            "blocking_factors": ["age"],
            "primary_conclusion": "Người dưới 14 tuổi HOÀN TOÀN KHÔNG BỊ TRUY CỨU TRÁCH NHIỆM HÌNH SỰ VÀ KHÔNG BỊ PHẠT TÙ đối với bất kỳ tội phạm nào.",
            "governing_law_basis": "Khoản 1 Điều 12 Bộ luật Hình sự 2015 (sửa đổi, bổ sung 2017) và Luật Tư pháp người chưa thành niên 2024 (có hiệu lực từ 01/01/2026).",
            "fact_ambiguity_warning": "Dữ kiện 'trọng thương' trong câu hỏi chỉ mang tính mô tả thương tích thực tế, chưa có kết luận giám định tỷ lệ tổn thương cơ thể (%) của cơ quan chuyên môn để định khung theo Điều 134 BLHS. Tuy nhiên, do chủ thể dưới 14 tuổi, dù tỷ lệ thương tật ở mức độ nào thì cũng KHÔNG bị truy cứu trách nhiệm hình sự.",
            "analysis_points": [
                "Theo Khoản 1 Điều 12 Bộ luật Hình sự 2015: Người từ đủ 16 tuổi trở lên phải chịu trách nhiệm hình sự về mọi tội phạm. Người từ đủ 14 tuổi đến dưới 16 tuổi chỉ chịu trách nhiệm hình sự về tội phạm rất nghiêm trọng hoặc đặc biệt nghiêm trọng do cố ý. Do đó, người dưới 14 tuổi CHƯA ĐỦ TUỔI CHỊU TRÁCH NHIỆM HÌNH SỰ đối với bất kỳ tội phạm nào.",
                "Luật Tư pháp người chưa thành niên 2024 (có hiệu lực từ 01/01/2026) tiếp tục củng cố nguyên tắc nhân đạo, bảo vệ trẻ em và ưu tiên áp dụng các biện pháp giáo dục, chuyển hướng thay vì truy cứu trách nhiệm hình sự.",
                "Về trách nhiệm bồi thường dân sự: Theo Điều 586 Bộ luật Dân sự 2015, người chưa đủ 15 tuổi gây thiệt hại mà còn cha mẹ thì cha mẹ phải bồi thường toàn bộ thiệt hại; nếu tài sản của cha mẹ không đủ mà con có tài sản riêng thì lấy tài sản đó để bồi thường phần còn thiếu.",
                "Về biện pháp xử lý hành chính/giáo dục: Tùy theo tính chất mức độ hành vi, người từ đủ 12 tuổi đến dưới 14 tuổi cố ý thực hiện hành vi có dấu hiệu tội phạm rất nghiêm trọng hoặc đặc biệt nghiêm trọng có thể bị xem xét áp dụng biện pháp đưa vào trường giáo dưỡng (theo Điều 92 Luật Xử lý vi phạm hành chính 2012, sửa đổi 2020) hoặc giáo dục tại xã, phường, thị trấn (Điều 90)."
            ],
            "remedy_laws": [
                {"law": "Bộ luật Hình sự 2015", "article": "Điều 12", "title": "Tuổi chịu trách nhiệm hình sự", "role": "Loại trừ trách nhiệm hình sự do chưa đủ tuổi"},
                {"law": "Bộ luật Dân sự 2015", "article": "Điều 586", "title": "Năng lực bồi thường thiệt hại của cá nhân", "role": "Cha mẹ/người giám hộ có nghĩa vụ bồi thường toàn bộ thiệt hại"},
                {"law": "Luật Xử lý vi phạm hành chính", "article": "Điều 90, 92", "title": "Giáo dục tại xã, phường và Đưa vào trường giáo dưỡng", "role": "Biện pháp giáo dục hành chính thay thế"},
                {"law": "Luật Tư pháp người chưa thành niên 2024", "article": "Chương xử lý chuyển hướng", "title": "Biện pháp xử lý chuyển hướng đối với người chưa thành niên", "role": "Khung pháp lý bảo vệ người chưa thành niên (hiệu lực 2026)"}
            ],
            "practical_guidance": "Gia đình cần chủ động thăm hỏi, thanh toán toàn bộ chi phí cấp cứu, điều trị phục hồi sức khỏe cho nạn nhân để khắc phục hậu quả dân sự; đồng thời phối hợp chặt chẽ với nhà trường và chính quyền địa phương để tăng cường giám sát, giáo dục con em."
        }, ensure_ascii=False),
        "2018-01-01",
        None,
        "1.0"
    ),
    (
        "RULE_CRIMINAL_AGE_14_TO_16",
        "Phạm vi chịu trách nhiệm hình sự người từ 14 đến dưới 16 tuổi (Khoản 2 Điều 12 BLHS 2015)",
        "criminal",
        "BLHS_2015",
        "Điều 12",
        json.dumps({
            "domain": "criminal",
            "facts": {
                "age": {"operator": "between", "min": 14, "max": 15}
            }
        }, ensure_ascii=False),
        "REQUIRE_CONDITION",
        json.dumps({
            "applicable": True,
            "requires_verification": True,
            "condition_description": "Người từ đủ 14 tuổi đến dưới 16 tuổi chỉ phải chịu trách nhiệm hình sự về tội phạm rất nghiêm trọng hoặc đặc biệt nghiêm trọng do cố ý thuộc 28 tội danh cụ thể tại Khoản 2 Điều 12 BLHS. Đối với Điều 134 (Cố ý gây thương tích), chỉ chịu trách nhiệm nếu thuộc Khoản 3, 4, 5 (thương tật từ 31% trở lên hoặc có tình tiết đặc biệt tăng nặng); KHÔNG chịu trách nhiệm hình sự về Khoản 1 (ít nghiêm trọng) và Khoản 2 (nghiêm trọng).",
            "governing_law_basis": "Khoản 2 Điều 12 và Điều 134 Bộ luật Hình sự 2015."
        }, ensure_ascii=False),
        "2018-01-01",
        None,
        "1.0"
    ),
    (
        "RULE_CIVIL_LIABILITY_UNDER_15",
        "Năng lực bồi thường thiệt hại người chưa đủ 15 tuổi (Điều 586 BLDS 2015)",
        "civil",
        "BLDS_2015",
        "Điều 586",
        json.dumps({
            "domain": "civil",
            "facts": {
                "age": {"operator": "<", "value": 15}
            }
        }, ensure_ascii=False),
        "SUBSTITUTE_LIABILITY",
        json.dumps({
            "applicable": True,
            "responsible_party": "cha_me_hoac_nguoi_giam_ho",
            "primary_conclusion": "Người chưa đủ 15 tuổi gây thiệt hại mà còn cha mẹ thì cha mẹ phải bồi thường toàn bộ thiệt hại; nếu tài sản cha mẹ không đủ mà con có tài sản riêng thì lấy tài sản đó để bồi thường phần còn thiếu.",
            "governing_law_basis": "Khoản 2 Điều 586 Bộ luật Dân sự 2015."
        }, ensure_ascii=False),
        "2017-01-01",
        None,
        "1.0"
    ),
    (
        "RULE_CIVIL_STATUTE_OF_LIMITATIONS",
        "Thời hiệu khởi kiện tranh chấp hợp đồng (Điều 429 BLDS 2015)",
        "civil",
        "BLDS_2015",
        "Điều 429",
        json.dumps({
            "domain": "civil",
            "subject": "contract_dispute"
        }, ensure_ascii=False),
        "LIMIT_THRESHOLD",
        json.dumps({
            "applicable": True,
            "primary_conclusion": "Thời hiệu khởi kiện để yêu cầu Tòa án giải quyết tranh chấp hợp đồng là 03 năm, kể từ ngày người có quyền yêu cầu biết hoặc phải biết quyền và lợi ích hợp pháp của mình bị xâm phạm.",
            "governing_law_basis": "Điều 429 Bộ luật Dân sự 2015."
        }, ensure_ascii=False),
        "2017-01-01",
        None,
        "1.0"
    ),
    (
        "RULE_LABOR_MIN_AGE",
        "Độ tuổi lao động tối thiểu và điều kiện tuyển dụng (Điều 143 BLLĐ 2019)",
        "labor",
        "BLLD_2019",
        "Điều 143",
        json.dumps({
            "domain": "labor",
            "facts": {
                "age": {"operator": "<", "value": 15}
            }
        }, ensure_ascii=False),
        "REQUIRE_CONDITION",
        json.dumps({
            "applicable": True,
            "primary_conclusion": "Người lao động chưa thành niên là người dưới 18 tuổi. Độ tuổi lao động tối thiểu thông thường là từ đủ 15 tuổi. Người từ đủ 13 tuổi đến dưới 15 tuổi chỉ được làm công việc nhẹ theo danh mục do Bộ LĐTBXH ban hành và phải có sự đồng ý của cha mẹ/người giám hộ.",
            "governing_law_basis": "Điều 143, Điều 145 Bộ luật Lao động 2019."
        }, ensure_ascii=False),
        "2021-01-01",
        None,
        "1.0"
    ),
    (
        "RULE_LABOR_PROBATION_LIMIT",
        "Thời gian thử việc tối đa theo trình độ chuyên môn (Điều 25 Bộ luật Lao động 2019)",
        "labor",
        "BLLD_2019",
        "Điều 25",
        json.dumps({
            "domain": "labor",
            "subject": "probation"
        }, ensure_ascii=False),
        "LIMIT_THRESHOLD",
        json.dumps({
            "applicable": True,
            "primary_conclusion": "Thời gian thử việc do hai bên thỏa thuận căn cứ vào tính chất và mức độ phức tạp của công việc nhưng chỉ được thử việc một lần và bảo đảm không vượt quá khung thời gian tối đa theo luật định.",
            "thresholds": {
                "enterprise_manager": "Tối đa 180 ngày đối với người quản lý doanh nghiệp",
                "college_or_higher": "Tối đa 60 ngày đối với công việc có chức danh nghề nghiệp cần trình độ chuyên môn từ cao đẳng trở lên",
                "intermediate_or_skilled_worker": "Tối đa 30 ngày đối với công việc có chức danh nghề nghiệp cần trình độ trung cấp, công nhân kỹ thuật",
                "other_work": "Tối đa 06 ngày làm việc đối với công việc khác",
                "contract_under_1_month": "Không áp dụng thử việc đối với hợp đồng lao động có thời hạn dưới 01 tháng"
            },
            "governing_law_basis": "Điều 25 Bộ luật Lao động 2019."
        }, ensure_ascii=False),
        "2021-01-01",
        None,
        "1.0"
    ),
    (
        "RULE_LABOR_MATERNITY_LEAVE",
        "Thời gian hưởng chế độ thai sản khi sinh con (Điều 139 Bộ luật Lao động 2019)",
        "labor",
        "BLLD_2019",
        "Điều 139",
        json.dumps({
            "domain": "labor",
            "subject": "maternity_leave"
        }, ensure_ascii=False),
        "STATUTORY_BENEFIT",
        json.dumps({
            "applicable": True,
            "primary_conclusion": "Lao động nữ được nghỉ thai sản trước và sau khi sinh con là 06 tháng; thời gian nghỉ trước khi sinh không quá 02 tháng. Trường hợp lao động nữ sinh đôi trở lên thì tính từ con thứ 2 trở đi, cứ mỗi con, người mẹ được nghỉ thêm 01 tháng.",
            "governing_law_basis": "Khoản 1 Điều 139 Bộ luật Lao động 2019 và Điều 34 Luật Bảo hiểm xã hội 2014."
        }, ensure_ascii=False),
        "2021-01-01",
        None,
        "1.0"
    ),
    (
        "RULE_ADMINISTRATIVE_LIMITATION",
        "Thời hiệu xử phạt vi phạm hành chính (Điều 6 Luật Xử lý vi phạm hành chính 2012)",
        "administrative",
        "LUAT_XLVPHC_2012",
        "Điều 6",
        json.dumps({
            "domain": "administrative",
            "subject": "limitation_period"
        }, ensure_ascii=False),
        "LIMIT_THRESHOLD",
        json.dumps({
            "applicable": True,
            "primary_conclusion": "Thời hiệu xử phạt vi phạm hành chính nói chung là 01 năm. Riêng vi phạm trong các lĩnh vực thuế, xây dựng, môi trường, khoáng sản, sở hữu trí tuệ... thời hiệu là 02 năm. Quá thời hiệu thì không ra quyết định xử phạt tiền nhưng vẫn có thể áp dụng biện pháp khắc phục hậu quả.",
            "governing_law_basis": "Điều 6, Điều 65 Luật Xử lý vi phạm hành chính 2012 (sửa đổi, bổ sung 2020)."
        }, ensure_ascii=False),
        "2013-07-01",
        None,
        "1.0"
    )
]

def migrate_and_seed():
    pool = get_db_pool()
    with pool.get_cursor(commit=True) as cur:
        logger.info("Chèn hoặc cập nhật danh mục quy tắc pháp lý mở rộng...")
        upsert_sql = """
            INSERT INTO legal_applicability_rules (
                rule_id, rule_name, domain, target_law_id, target_article,
                condition_schema, effect_type, legal_decision, effective_from, effective_to, version
            ) VALUES %s
            ON CONFLICT (rule_id) DO UPDATE SET
                rule_name = EXCLUDED.rule_name,
                domain = EXCLUDED.domain,
                target_law_id = EXCLUDED.target_law_id,
                target_article = EXCLUDED.target_article,
                condition_schema = EXCLUDED.condition_schema,
                effect_type = EXCLUDED.effect_type,
                legal_decision = EXCLUDED.legal_decision,
                effective_from = EXCLUDED.effective_from,
                effective_to = EXCLUDED.effective_to,
                version = EXCLUDED.version,
                updated_at = CURRENT_TIMESTAMP;
        """
        execute_values(cur, upsert_sql, RULES_DATA)
        logger.info(f"Đã seed thành công {len(RULES_DATA)} quy tắc vào bảng legal_applicability_rules!")

        cur.execute("SELECT rule_id, rule_name, domain, effect_type FROM legal_applicability_rules;")
        rows = cur.fetchall()
        for r in rows:
            logger.info(f" - {r['rule_id']}: {r['rule_name']} [{r['domain']} -> {r['effect_type']}]")

if __name__ == "__main__":
    migrate_and_seed()
