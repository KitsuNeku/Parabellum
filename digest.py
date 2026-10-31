from datetime import date, timedelta

import mailer
import preferences
from db import execute_query, log_audit, get_company_settings


def _summary(db_config):
    low = execute_query(db_config, """
        SELECT material_name, unit, current_stock, reorder_level FROM materials
        WHERE current_stock <= reorder_level ORDER BY current_stock LIMIT 10;
    """, fetch=True)
    since = date.today() - timedelta(days=7)
    txn = execute_query(db_config, """
        SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total,
               COUNT(*) FILTER (WHERE payment_status <> 'Paid') AS unpaid
        FROM transactions WHERE txn_date >= %s;
    """, (since,), fetch=True)[0]
    moves = execute_query(db_config, """
        SELECT COUNT(*) FILTER (WHERE movement_type = 'RECEIPT') AS stock_in,
               COUNT(*) FILTER (WHERE movement_type = 'ISSUANCE') AS stock_out,
               COUNT(*) FILTER (WHERE delivery_failed_at >= %s) AS failed
        FROM stock_movements WHERE movement_date >= %s;
    """, (since, since), fetch=True)[0]
    restock = execute_query(db_config, """
        SELECT m.material_name, m.unit, f.predicted_demand - m.current_stock AS need
        FROM forecast_results f JOIN materials m ON m.material_id = f.material_id
        WHERE f.forecast_month = (SELECT MAX(forecast_month) FROM forecast_results)
          AND f.predicted_demand > m.current_stock
        ORDER BY need DESC LIMIT 5;
    """, fetch=True)
    lines = [f"Week of {since:%B %d} to {date.today():%B %d, %Y}", ""]
    lines += [f"Client transactions: {txn['n']} (PHP {float(txn['total']):,.2f}), {txn['unpaid']} not yet paid",
              f"Stock In: {moves['stock_in']}   Stock Out: {moves['stock_out']}   Failed deliveries: {moves['failed']}", ""]
    lines.append("Low stock:" if low else "Low stock: none")
    lines += [f"  - {r['material_name']}: {float(r['current_stock']):g} {r['unit']} (reorder at {float(r['reorder_level']):g})" for r in low]
    lines.append("")
    lines.append("Forecast restock needs:" if restock else "Forecast restock needs: none")
    lines += [f"  - {r['material_name']}: {float(r['need']):,.0f} {r['unit']}" for r in restock]
    return "\n".join(lines)


def send_weekly(db_config):
    if not mailer.is_configured():
        return 0
    users = execute_query(db_config, """
        SELECT user_id, username, full_name, email, preferences FROM users
        WHERE is_active AND email IS NOT NULL AND email <> '';
    """, fetch=True)
    recipients = [u for u in users if preferences.normalize(u["preferences"] or {})["notify"]["emailDigest"]]
    if not recipients:
        return 0
    company = get_company_settings(db_config)["company_name"]
    body = _summary(db_config)
    sent = 0
    for u in recipients:
        try:
            mailer.send(u["email"], f"{company} - weekly summary",
                        f"Hi {u['full_name'] or u['username']},\n\n{body}\n\nParabellum ISOS")
            sent += 1
        except Exception:
            pass
    execute_query(db_config, "UPDATE company_settings SET last_digest_at = CURRENT_TIMESTAMP WHERE id = 1;")
    log_audit(db_config, "EMAIL_DIGEST_SENT", f"Weekly summary sent to {sent} user(s).")
    return sent
