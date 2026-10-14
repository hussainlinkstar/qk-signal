import html2canvas from "html2canvas";
import jsPDF from "jspdf";

type RenderElementToPdfOptions = {
  element: HTMLElement;
  fileName: string;
  reportTitle: string;
  subtitleLines?: string[];
  date?: Date;
};

export const renderElementToPdf = async ({
  element,
  fileName,
  reportTitle,
  subtitleLines = [],
  date = new Date(),
}: RenderElementToPdfOptions): Promise<void> => {
  const originalBg = element.style.backgroundColor;
  element.style.backgroundColor = "#f8fafc";

  try {
    const canvas = await html2canvas(element, {
      scale: 2,
      backgroundColor: "#f8fafc",
      onclone: (document) => {
        document.querySelectorAll(".text-white, .text-slate-300, .text-slate-400").forEach((el) => {
          (el as HTMLElement).style.color = "#00040e";
        });
        document.querySelectorAll(".bg-slate-900, .bg-slate-950").forEach((el) => {
          (el as HTMLElement).style.backgroundColor = "#ffffff";
        });
        document.querySelectorAll(".border-slate-800").forEach((el) => {
          (el as HTMLElement).style.borderColor = "#e2e8f0";
        });
      },
    });

    const imgData = canvas.toDataURL("image/png");
    const pdf = new jsPDF("p", "mm", "a4");
    const pdfWidth = pdf.internal.pageSize.getWidth();
    const pdfHeight = pdf.internal.pageSize.getHeight();
    const canvasWidth = canvas.width;
    const canvasHeight = canvas.height;
    const ratio = canvasWidth / canvasHeight;
    const imgWidth = pdfWidth - 20;
    const imgHeight = imgWidth / ratio;

    let heightLeft = imgHeight;

    pdf.setFontSize(18);
    pdf.setTextColor("#00040e");
    pdf.text(reportTitle, 10, 10);

    pdf.setFontSize(10);
    pdf.setTextColor("#64748b");
    subtitleLines.forEach((line, index) => {
      pdf.text(line, 10, 15 + index * 5);
    });
    pdf.text(`Date: ${date.toLocaleDateString()}`, pdfWidth - 10, 10, { align: "right" });

    const imageTopOffset = 25;
    pdf.addImage(imgData, "PNG", 10, imageTopOffset, imgWidth, imgHeight);
    heightLeft -= pdfHeight - imageTopOffset;

    while (heightLeft >= 0) {
      const position = heightLeft - imgHeight;
      pdf.addPage();
      pdf.addImage(imgData, "PNG", 10, position, imgWidth, imgHeight);
      heightLeft -= pdfHeight;
    }

    pdf.save(fileName);
  } finally {
    element.style.backgroundColor = originalBg;
  }
};
