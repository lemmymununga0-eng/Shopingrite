# Converts a .docx to .pdf with Microsoft Word (used only to check the layout; the .docx is the deliverable).
#   powershell -File research\paper\docx_to_pdf.ps1 -In paper.docx -Out paper.pdf
param([Parameter(Mandatory = $true)][string]$In, [Parameter(Mandatory = $true)][string]$Out)
$word = New-Object -ComObject Word.Application
$word.Visible = $false
try {
  $doc = $word.Documents.Open((Resolve-Path $In).Path, $false, $true)
  $doc.ExportAsFixedFormat([System.IO.Path]::GetFullPath($Out), 17)     # 17 = wdExportFormatPDF
  $pages = $doc.ComputeStatistics(2)                                    # 2 = wdStatisticPages
  $words = $doc.ComputeStatistics(0)                                    # 0 = wdStatisticWords
  Write-Output "pages=$pages words=$words"
  $doc.Close($false)
} finally { $word.Quit() }
