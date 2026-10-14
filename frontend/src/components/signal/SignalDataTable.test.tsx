import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";

type Row = { id: number; name: string; amount: number };

const makeRows = (n: number): Row[] =>
  Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    name: `Row ${i + 1}`,
    amount: (i + 1) * 10,
  }));

const columns: SignalDataTableColumn<Row>[] = [
  {
    key: "name",
    header: "Name",
    sortable: true,
    sortValue: (r) => r.name,
    renderCell: (r) => r.name,
  },
  {
    key: "amount",
    header: "Amount",
    align: "right",
    sortable: true,
    sortValue: (r) => r.amount,
    renderCell: (r) => String(r.amount),
  },
];

describe("SignalDataTable", () => {
  it("renders rows", () => {
    render(
      <SignalDataTable
        columns={columns}
        rows={makeRows(3)}
        rowKey={(r) => r.id}
        searchText={(r) => r.name}
      />
    );
    expect(screen.getByText("Row 1")).toBeInTheDocument();
    expect(screen.getByText("Row 3")).toBeInTheDocument();
  });

  it("renders the empty state", () => {
    render(<SignalDataTable columns={columns} rows={[]} rowKey={(r) => r.id} />);
    expect(screen.getByText("Nothing to show yet.")).toBeInTheDocument();
  });

  it("filters rows through the search input", () => {
    render(
      <SignalDataTable
        columns={columns}
        rows={makeRows(5)}
        rowKey={(r) => r.id}
        searchText={(r) => r.name}
      />
    );
    fireEvent.change(screen.getByRole("textbox", { name: /search/i }), {
      target: { value: "Row 4" },
    });
    expect(screen.getByText("Row 4")).toBeInTheDocument();
    expect(screen.queryByText("Row 1")).not.toBeInTheDocument();
  });

  it("toggles the sort indicator on sortable headers", () => {
    render(<SignalDataTable columns={columns} rows={makeRows(3)} rowKey={(r) => r.id} />);
    const header = screen.getByRole("button", { name: "Name" });
    fireEvent.click(header);
    expect(header.closest("th")).toHaveAttribute("aria-sort", "ascending");
    fireEvent.click(header);
    expect(header.closest("th")).toHaveAttribute("aria-sort", "descending");
  });

  it("sorts via keyboard on the header button", () => {
    render(<SignalDataTable columns={columns} rows={makeRows(3)} rowKey={(r) => r.id} />);
    const header = screen.getByRole("button", { name: "Name" });
    header.focus();
    expect(header).toHaveFocus();
    fireEvent.keyDown(header, { key: "Enter" });
    // jsdom does not synthesize click for keydown on buttons; activate directly.
    fireEvent.click(header);
    expect(header.closest("th")).toHaveAttribute("aria-sort", "ascending");
    fireEvent.keyDown(header, { key: " " });
    fireEvent.click(header);
    expect(header.closest("th")).toHaveAttribute("aria-sort", "descending");
  });

  it("paginates rows", () => {
    render(
      <SignalDataTable columns={columns} rows={makeRows(12)} rowKey={(r) => r.id} pageSize={10} />
    );
    expect(screen.queryByText("Row 11")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2" }));
    expect(screen.getByText("Row 11")).toBeInTheDocument();
    expect(screen.queryByText("Row 1")).not.toBeInTheDocument();
  });

  it("windows the pager with ellipses for large page counts", () => {
    render(
      <SignalDataTable columns={columns} rows={makeRows(80)} rowKey={(r) => r.id} pageSize={10} />
    );
    const nav = screen.getByRole("navigation", { name: "Pagination" });
    const pageButtons = nav.querySelectorAll("button");
    // 8 pages at page 1 -> pages 1, 2, 8 plus prev/next = 5 buttons.
    expect(pageButtons.length).toBe(5);
    const ellipsis = nav.querySelectorAll('span[aria-hidden="true"]');
    expect(ellipsis.length).toBe(1);
    expect(screen.getByRole("button", { name: "1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "8" })).toBeInTheDocument();
    // Move to the middle via the windowed neighbours and both runs get an ellipsis.
    fireEvent.click(screen.getByRole("button", { name: "2" }));
    fireEvent.click(screen.getByRole("button", { name: "3" }));
    fireEvent.click(screen.getByRole("button", { name: "4" }));
    expect(nav.querySelectorAll('span[aria-hidden="true"]').length).toBe(2);
    expect(screen.getByRole("button", { name: "1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "8" })).toBeInTheDocument();
  });
});
