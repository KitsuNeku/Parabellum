"""
Parabellum ISOS - Report Generation
=================================================================
Objective 2.3 / DFD 5.0: stock status, material movement (stock in,
stock out, back order/returns), customer, project, transaction, and
forecast reports.

Design: every report type has ONE function that queries the database and
returns (title, subtitle, columns, rows) with values already formatted as
display strings (peso signs, percentages, etc. included). The on-screen
preview, the PDF, and the Excel file all read from that SAME function -
so the three formats can never disagree with each other, and a defense
panelist comparing "does the PDF match what's on screen" always gets yes.
"""

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from xml.sax.saxutils import escape
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from mlr_model import execute_query

PRIMARY_HEX = "8B1E1E"   # matches --primary in styles.css


def _peso(n):
    return f"\u20b1{float(n or 0):,.2f}"


def _num(n):
    return f"{float(n or 0):,.2f}".rstrip("0").rstrip(".") if "." in f"{float(n or 0):,.2f}" else f"{float(n or 0):,.0f}"


# =================================================================
# Report builders - one per report type. Each returns:
# title, subtitle, columns (list[str]), rows (list[list[str]])
# =================================================================
def build_inventory_report(db_config):
    rows = execute_query(db_config, """
        SELECT material_name, category, current_stock, unit, unit_cost,
               reorder_level
        FROM materials ORDER BY material_name;
    """, fetch=True)
    out = []
    for r in rows:
        qty = float(r["current_stock"])
        value = qty * float(r["unit_cost"])
        status = "Out of Stock" if qty <= 0 else ("Low Stock" if qty <= float(r["reorder_level"]) else "In Stock")
        out.append([r["material_name"], r["category"] or "\u2014",
                    f"{qty:g} {r['unit']}", _peso(r["unit_cost"]), _peso(value), status])
    return ("Inventory Report", "Stock levels and valuation",
            ["Item", "Category", "Qty", "Unit Price", "Value", "Status"], out)


def build_customer_report(db_config):
    rows = execute_query(db_config, """
        SELECT c.name, c.contact_person, c.status,
               (SELECT COUNT(*) FROM projects p WHERE p.customer_id = c.customer_id) AS projects,
               (SELECT COUNT(*) FROM transactions t WHERE t.customer_id = c.customer_id) AS txns
        FROM customers c ORDER BY c.name;
    """, fetch=True)
    out = [[r["name"], r["contact_person"] or "\u2014", r["status"],
            str(int(r["projects"])), str(int(r["txns"]))] for r in rows]
    return ("Customer Report", "Accounts and activity",
            ["Customer", "Contact", "Status", "Projects", "Transactions"], out)


def build_project_report(db_config):
    """
    One row per project: its status and budget, PLUS what was stocked out to
    it, what came back as back orders, and what that does to the budget.

    How materials are tied to a project: a Stock Out stores the project code
    (e.g. PRJ-301) in stock_movements.remarks, and a Record Return stores it
    in back_orders.stock_out_ref - so both are matched on project_code.

    "Stocked Out (less Back Orders)": per material, quantity stocked out minus
    quantity back-ordered, e.g. "Angle Bar: 50 - 5 = 45 pcs". Every back order
    reduces the net quantity (the material did physically come back).

    Budget liquidation: Budget Used = cost of everything stocked out (qty x
    the material's CURRENT unit cost - cost history isn't stored) MINUS what
    was credited back for returns that have been decided:
      * Replaced   -> the replaced quantity (it went back on the shelf)
                      x unit cost is credited back;
      * Reimbursed -> the peso amount actually refunded is credited back;
      * Pending    -> nothing is credited yet (noted as "Pending decision").
    Budget Left = Budget - Budget Used (can go negative if over budget).
    The Return Note column says, per back order, whether it was Replaced or
    Reimbursed.
    """
    projects = execute_query(db_config, """
        SELECT p.project_code, p.project_name, c.name AS customer_name, p.status,
               p.progress, p.budget, p.end_date
        FROM projects p LEFT JOIN customers c ON c.customer_id = p.customer_id
        WHERE p.project_code IS NOT NULL
        ORDER BY p.start_date DESC;
    """, fetch=True)

    issued = execute_query(db_config, """
        SELECT sm.remarks AS ref, m.material_id, m.material_name, m.unit, m.unit_cost,
               SUM(sm.quantity) AS qty
        FROM stock_movements sm JOIN materials m ON m.material_id = sm.material_id
        WHERE sm.movement_type = 'ISSUANCE' AND sm.remarks IS NOT NULL
        GROUP BY sm.remarks, m.material_id, m.material_name, m.unit, m.unit_cost;
    """, fetch=True)

    returns = execute_query(db_config, """
        SELECT bo.stock_out_ref AS ref, m.material_id, m.material_name, m.unit, m.unit_cost,
               bo.quantity, bo.disposition, bo.replaced_qty, bo.reimbursed_amount
        FROM back_orders bo JOIN materials m ON m.material_id = bo.material_id
        WHERE bo.stock_out_ref IS NOT NULL
        ORDER BY bo.return_date, bo.back_order_id;
    """, fetch=True)

    out_by_proj, ret_by_proj = {}, {}
    for r in issued:
        out_by_proj.setdefault(r["ref"], []).append(r)
    for r in returns:
        ret_by_proj.setdefault(r["ref"], []).append(r)

    status_map = {"Ongoing": "In Progress", "Completed": "Completed"}
    out = []
    for p in projects:
        code = p["project_code"]
        items = {}   # material_id -> [name, unit, stocked_out, back_ordered]
        issued_cost = 0.0
        for r in out_by_proj.get(code, []):
            qty = float(r["qty"])
            issued_cost += qty * float(r["unit_cost"] or 0)
            items[r["material_id"]] = [r["material_name"], r["unit"], qty, 0.0]

        credit = 0.0
        notes = []
        for r in ret_by_proj.get(code, []):
            qty = float(r["quantity"])
            entry = items.setdefault(r["material_id"], [r["material_name"], r["unit"], 0.0, 0.0])
            entry[3] += qty
            label = f"{r['material_name']} {qty:g} {r['unit']}"
            if r["disposition"] == "Replaced":
                rq = float(r["replaced_qty"] if r["replaced_qty"] is not None else qty)
                amt = rq * float(r["unit_cost"] or 0)
                credit += amt
                notes.append(f"{label}: Replaced ({rq:g} {r['unit']} back to stock, {_peso(amt)} credited)")
            elif r["disposition"] == "Reimbursed":
                amt = float(r["reimbursed_amount"] or 0)
                credit += amt
                notes.append(f"{label}: Reimbursed ({_peso(amt)} refunded)")
            else:
                notes.append(f"{label}: Pending decision")

        lines = []
        for name, unit, so, bo in items.values():
            if bo:
                lines.append(f"{name}: {so:g} \u2212 {bo:g} = {so - bo:g} {unit}")
            else:
                lines.append(f"{name}: {so:g} {unit}")

        budget = float(p["budget"] or 0)
        used = issued_cost - credit
        out.append([
            p["project_name"], p["customer_name"] or "\u2014",
            status_map.get(p["status"], p["status"]), f"{int(p['progress'] or 0)}%",
            _peso(budget), str(p["end_date"]) if p["end_date"] else "\u2014",
            "\n".join(lines) if lines else "None stocked out",
            _peso(used), _peso(budget - used),
            "\n".join(notes) if notes else "No returns",
        ])
    return ("Project Report", "Status, budgets, materials stocked out and returns",
            ["Project", "Customer", "Status", "Progress", "Budget", "Due",
             "Stocked Out (less Back Orders)", "Budget Used", "Budget Left", "Return Note"], out)


def build_transaction_report(db_config):
    rows = execute_query(db_config, """
        SELECT t.transaction_id, c.name AS customer_name, t.material_name,
               t.quantity, t.unit_price, t.payment_status, t.txn_date
        FROM transactions t LEFT JOIN customers c ON c.customer_id = t.customer_id
        ORDER BY t.txn_date DESC, t.transaction_id DESC;
    """, fetch=True)
    out = []
    for r in rows:
        total = float(r["quantity"] or 0) * float(r["unit_price"] or 0) * 1.12  # incl. 12% VAT
        out.append([f"TXN-{r['transaction_id']:04d}", r["customer_name"] or "\u2014",
                    r["material_name"] or "\u2014", _num(r["quantity"]),
                    _peso(total), r["payment_status"] or "Pending",
                    str(r["txn_date"]) if r["txn_date"] else "\u2014"])
    return ("Client Transaction Report", "Invoices incl. 12% VAT",
            ["Invoice", "Customer", "Material", "Qty", "Total", "Status", "Date"], out)


def build_stock_in_report(db_config):
    """
    Every RECEIPT movement (materials coming into the warehouse), newest
    first. Same stock_movements table the Inventory page's Stock In table
    reads - this is a formatted/exportable view of the identical rows.
    """
    rows = execute_query(db_config, """
        SELECT m.material_name, m.category, sm.quantity, m.unit,
               sm.movement_date, sm.remarks, sm.recorded_by
        FROM stock_movements sm
        JOIN materials m ON m.material_id = sm.material_id
        WHERE sm.movement_type = 'RECEIPT'
        ORDER BY sm.movement_date DESC, sm.movement_id DESC;
    """, fetch=True)
    out = [[r["material_name"], r["category"] or "\u2014",
            f"{float(r['quantity']):g} {r['unit']}",
            str(r["movement_date"]) if r["movement_date"] else "\u2014",
            r["remarks"] or "\u2014", r["recorded_by"] or "\u2014"] for r in rows]
    return ("Stock In Report", "Materials received into inventory",
            ["Item", "Category", "Qty Received", "Date", "Remarks", "Recorded By"], out)


def build_stock_out_report(db_config):
    """
    Every ISSUANCE movement (materials issued out to a project/customer),
    newest first. `remarks` holds the project/reference string entered at
    issuance time (see _apply_movement in app.py - stock-out does not set
    the stock_movements.project_id foreign key, only this free-text field).
    """
    rows = execute_query(db_config, """
        SELECT m.material_name, m.category, sm.quantity, m.unit,
               sm.movement_date, sm.remarks, sm.recorded_by
        FROM stock_movements sm
        JOIN materials m ON m.material_id = sm.material_id
        WHERE sm.movement_type = 'ISSUANCE'
        ORDER BY sm.movement_date DESC, sm.movement_id DESC;
    """, fetch=True)
    out = [[r["material_name"], r["category"] or "\u2014",
            f"{float(r['quantity']):g} {r['unit']}",
            str(r["movement_date"]) if r["movement_date"] else "\u2014",
            r["remarks"] or "\u2014", r["recorded_by"] or "\u2014"] for r in rows]
    return ("Stock Out Report", "Materials issued to projects/customers",
            ["Item", "Category", "Qty Issued", "Date", "Project / Reference", "Recorded By"], out)


def build_back_order_report(db_config):
    """
    Every back order - materials returned by a customer/project (the
    Inventory page's "Back Orders (Returns from Customers)" table), from
    its own back_orders table (not stock_movements - see the Back Orders
    redesign in schema.sql). Not a supplier re-order; see the matching
    comment on the inventory page's Record Return modal. Includes a
    Received By column - the staff account that processed the return
    (it's the logged-in user at the time, same as Recorded By - the
    Record Return modal auto-fills it rather than asking for it) - and a
    Disposition column: "Replaced" (added back to stock), "Reimbursed"
    (written off), or "Pending" if not yet decided.
    """
    rows = execute_query(db_config, """
        SELECT m.material_name, m.category, bo.quantity, m.unit,
               bo.return_date, bo.remarks, bo.recorded_by, bo.back_order_by, bo.disposition,
               bo.replaced_qty, bo.reimbursed_amount
        FROM back_orders bo
        JOIN materials m ON m.material_id = bo.material_id
        ORDER BY bo.return_date DESC, bo.back_order_id DESC;
    """, fetch=True)

    def _disposition_cell(r):
        # "Replaced" / "Reimbursed" alone doesn't say how much - the
        # disposition popup on the Inventory page now collects that (Qty
        # Replaced, or Amount Reimbursed in pesos), so show it here too.
        if r["disposition"] == "Replaced" and r["replaced_qty"] is not None:
            return f"Replaced ({float(r['replaced_qty']):g} {r['unit']})"
        if r["disposition"] == "Reimbursed" and r["reimbursed_amount"] is not None:
            return f"Reimbursed (\u20b1{float(r['reimbursed_amount']):,.2f})"
        return r["disposition"] or "Pending"

    out = [[r["material_name"], r["category"] or "\u2014",
            f"{float(r['quantity']):g} {r['unit']}",
            str(r["return_date"]) if r["return_date"] else "\u2014",
            r["remarks"] or "\u2014", r["back_order_by"] or "\u2014",
            r["recorded_by"] or "\u2014", _disposition_cell(r)] for r in rows]
    return ("Back Order Report", "Materials returned from customers/projects",
            ["Item", "Category", "Qty Returned", "Date", "Reason / Reference", "Received By", "Recorded By", "Disposition"], out)



def build_forecast_report(db_config):
    rows = execute_query(db_config, """
        SELECT m.material_name, f.forecast_month, f.predicted_demand,
               m.current_stock, m.unit
        FROM forecast_results f
        JOIN materials m ON m.material_id = f.material_id
        WHERE f.forecast_month = (SELECT MAX(forecast_month) FROM forecast_results)
        ORDER BY m.material_name;
    """, fetch=True)
    metrics = execute_query(db_config, """
        SELECT mae, rmse, mape, r2 FROM model_metrics
        ORDER BY evaluated_at DESC LIMIT 1;
    """, fetch=True)
    out = []
    for r in rows:
        pred = float(r["predicted_demand"])
        stock = float(r["current_stock"])
        trend = "\u2014"
        out.append([r["material_name"], str(r["forecast_month"]),
                    f"{pred:g} {r['unit']}", f"{stock:g} {r['unit']}", trend,
                    f"R\u00b2 {metrics[0]['r2']}" if metrics else "\u2014"])
    subtitle = "Predicted demand for the coming month"
    if metrics:
        m = metrics[0]
        subtitle += f" \u2014 MAE {m['mae']}, RMSE {m['rmse']}, MAPE {m['mape']}%, R\u00b2 {m['r2']}"
    if not out:
        subtitle += " (no forecast has been run yet \u2014 visit the Forecasting page first)"
    return ("Demand Forecast Report", subtitle,
            ["Material", "Month", "Predicted", "Current Stock", "Trend", "Model Fit"], out)


REPORT_BUILDERS = {
    "inventory":   build_inventory_report,
    "customer":    build_customer_report,
    "project":     build_project_report,
    "transaction": build_transaction_report,
    "stock-in":    build_stock_in_report,
    "stock-out":   build_stock_out_report,
    "back-order":  build_back_order_report,
    "forecast":    build_forecast_report,
}


# =================================================================
# File generators - PDF (reportlab) and Excel (openpyxl)
# =================================================================
def generate_pdf(title, subtitle, columns, rows, generated_by="System"):
    buf = io.BytesIO()
    # Wide reports (many columns) or cells with several lines (the Project
    # Report lists items per project) need wrapped text, proportional column
    # widths and a landscape page; everything else keeps the original layout.
    wide = len(columns) > 7 or any("\n" in str(c) for row in rows for c in row)
    page = landscape(letter) if wide else letter
    doc = SimpleDocTemplate(buf, pagesize=page,
                             topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                             leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    header_style = ParagraphStyle("Header", parent=styles["Heading1"],
                                   textColor=colors.HexColor(f"#{PRIMARY_HEX}"), fontSize=16)
    sub_style = ParagraphStyle("Sub", parent=styles["Normal"], textColor=colors.grey, fontSize=9)
    meta_style = ParagraphStyle("Meta", parent=styles["Normal"], fontSize=8,
                                 textColor=colors.grey, alignment=2)  # right-aligned

    generated = datetime.now().strftime("%B %d, %Y  %I:%M %p")
    story = [
        Paragraph("PARABELLUM STEEL &amp; IRON WORKS", header_style),
        Paragraph(subtitle, sub_style),
        Spacer(1, 4),
        Paragraph(f"Generated {generated} by {generated_by}", meta_style),
        Spacer(1, 12),
    ]

    table_data = [columns] + rows if rows else [columns, ["No records found."] + [""] * (len(columns) - 1)]
    if wide:
        cell_style = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=7, leading=9)
        head_style = ParagraphStyle("HeadCell", parent=cell_style, textColor=colors.white,
                                    fontName="Helvetica-Bold")
        def _p(v, st):
            return Paragraph(escape(str(v)).replace("\n", "<br/>"), st)
        table_data = [[_p(c, head_style) for c in columns]] + \
                     [[_p(c, cell_style) for c in row] for row in (table_data[1:])]
    usable = page[0] - 1.2 * inch
    if wide:
        weights = []
        for i, col in enumerate(columns):
            longest = max([len(col)] + [len(line) for row in rows for line in str(row[i]).split("\n")])
            weights.append(min(max(longest, 6), 34) ** 0.7)
        col_widths = [usable * w / sum(weights) for w in weights]
    else:
        col_widths = [usable / len(columns)] * len(columns)
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{PRIMARY_HEX}")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F1E8")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4D9C4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP" if wide else "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tbl)
    doc.title = title
    doc.build(story)
    buf.seek(0)
    return buf


def generate_excel(title, subtitle, columns, rows, generated_by="System"):
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]  # Excel sheet-name limit

    header_fill = PatternFill("solid", fgColor=PRIMARY_HEX)
    header_font = Font(color="FFFFFF", bold=True)
    title_font = Font(bold=True, size=14, color=PRIMARY_HEX)

    ws.merge_cells("A1:" + get_column_letter(len(columns)) + "1")
    ws["A1"] = "PARABELLUM STEEL & IRON WORKS"
    ws["A1"].font = title_font

    ws.merge_cells("A2:" + get_column_letter(len(columns)) + "2")
    ws["A2"] = subtitle
    ws["A2"].font = Font(italic=True, color="666666")

    generated = datetime.now().strftime("%B %d, %Y  %I:%M %p")
    ws.merge_cells("A3:" + get_column_letter(len(columns)) + "3")
    ws["A3"] = f"Generated {generated} by {generated_by}"
    ws["A3"].font = Font(size=9, color="999999")

    header_row = 5
    for i, col in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=i, value=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    display_rows = rows if rows else [["No records found."] + [""] * (len(columns) - 1)]
    for r, row in enumerate(display_rows, start=header_row + 1):
        for c, val in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=val)
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    for i, col in enumerate(columns, start=1):
        width = max(len(col), *(len(line) for row in display_rows for line in str(row[i - 1]).split("\n"))) + 3
        ws.column_dimensions[get_column_letter(i)].width = min(width, 40)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
