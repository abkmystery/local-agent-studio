Add-Type -AssemblyName System.Drawing

$size = 512
$bitmap = [System.Drawing.Bitmap]::new($size, $size)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.Clear([System.Drawing.Color]::Transparent)

$path = [System.Drawing.Drawing2D.GraphicsPath]::new()
$radius = 140
$rect = [System.Drawing.RectangleF]::new(24, 24, 464, 464)
$diameter = $radius * 2
$path.AddArc($rect.Left, $rect.Top, $diameter, $diameter, 180, 90)
$path.AddArc($rect.Right - $diameter, $rect.Top, $diameter, $diameter, 270, 90)
$path.AddArc($rect.Right - $diameter, $rect.Bottom - $diameter, $diameter, $diameter, 0, 90)
$path.AddArc($rect.Left, $rect.Bottom - $diameter, $diameter, $diameter, 90, 90)
$path.CloseFigure()

$gradient = [System.Drawing.Drawing2D.LinearGradientBrush]::new(
  [System.Drawing.PointF]::new(55, 45),
  [System.Drawing.PointF]::new(470, 480),
  [System.Drawing.ColorTranslator]::FromHtml('#7467F0'),
  [System.Drawing.ColorTranslator]::FromHtml('#20B8A5')
)
$graphics.FillPath($gradient, $path)

$white = [System.Drawing.Pen]::new([System.Drawing.Color]::White, 32)
$white.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
$white.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
$graphics.DrawLines($white, @(
  [System.Drawing.PointF]::new(160, 160),
  [System.Drawing.PointF]::new(160, 328),
  [System.Drawing.PointF]::new(208, 376),
  [System.Drawing.PointF]::new(352, 376)
))

$mesh = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(215, 255, 255, 255), 20)
$mesh.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
$mesh.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
$graphics.DrawLines($mesh, @(
  [System.Drawing.PointF]::new(176, 200),
  [System.Drawing.PointF]::new(296, 152),
  [System.Drawing.PointF]::new(360, 272),
  [System.Drawing.PointF]::new(248, 336)
))

$nodeBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
foreach ($point in @(@(160,160), @(304,152), @(360,272), @(248,336))) {
  $graphics.FillEllipse($nodeBrush, $point[0] - 40, $point[1] - 40, 80, 80)
}

$output = Join-Path $PSScriptRoot '..\build\icon.png'
$bitmap.Save($output, [System.Drawing.Imaging.ImageFormat]::Png)

$nodeBrush.Dispose(); $mesh.Dispose(); $white.Dispose(); $gradient.Dispose(); $path.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
Write-Host "Generated $output"
