# Quality checks on a .docx with Microsoft Word: page and word counts, tables, figures, spelling and grammar errors.
#   powershell -File research\paper\qa_docx.ps1 -In manuscript.docx
param([Parameter(Mandatory = $true)][string]$In)
$word = New-Object -ComObject Word.Application
$word.Visible = $false
try {
  $doc = $word.Documents.Open((Resolve-Path $In).Path, $false, $true)
  $doc.Repaginate()
  Write-Output ("pages={0} words={1} tables={2} figures={3} paragraphs={4}" -f $doc.ComputeStatistics(2), $doc.ComputeStatistics(0), $doc.Tables.Count, $doc.InlineShapes.Count, $doc.Paragraphs.Count)
  $errs = $doc.SpellingErrors
  Write-Output ("spelling errors: {0}" -f $errs.Count)
  $seen = @{}
  foreach ($e in $errs) { $t = $e.Text; if (-not $seen.ContainsKey($t)) { $seen[$t] = 0 }; $seen[$t]++ }
  $seen.GetEnumerator() | Sort-Object Name | ForEach-Object { Write-Output ("  {0} x{1}" -f $_.Name, $_.Value) }
  Write-Output ("grammar errors: {0}" -f $doc.GrammaticalErrors.Count)
  $i = 0
  foreach ($g in $doc.GrammaticalErrors) { if ($i -lt 40) { Write-Output ("  G: " + ($g.Text -replace "\s+", " ")) }; $i++ }
  $alt = 0; foreach ($s in $doc.InlineShapes) { if ($s.AlternativeText) { $alt++ } }
  Write-Output ("figures with alt text: {0} of {1}" -f $alt, $doc.InlineShapes.Count)
  $doc.Close($false)
} finally { $word.Quit() }
