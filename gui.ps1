if ([System.Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') {
    $hostExe = (Get-Process -Id $PID).Path
    Start-Process -FilePath $hostExe -WorkingDirectory (Get-Location) -ArgumentList @(
        '-STA',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        $PSCommandPath
    ) | Out-Null
    exit
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:MP4_COMP_EVENT_MODE = '1'

$script:EventPrefix = '__MP4_COMP_EVENT__'
$script:ScriptDir = Split-Path -Parent $PSCommandPath
$script:CompressScript = Join-Path $script:ScriptDir 'compress.py'
$script:CurrentProcess = $null
$script:CurrentStdOutFile = $null
$script:CurrentStdErrFile = $null
$script:LastStdOutLength = 0
$script:LastStdErrLength = 0
$script:CurrentProbeData = $null
$script:CurrentProbePath = $null
$script:Jobs = New-Object System.Collections.ArrayList
$script:CurrentJob = $null
$script:LastBackendResult = $null
$script:LastProgressCurrentText = ''
$script:LastProgressTotalText = ''

function Show-ErrorMessage {
    param(
        [string]$Message,
        [string]$Title = 'mp4-comp'
    )

    [void][System.Windows.Forms.MessageBox]::Show(
        $Message,
        $Title,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
}

try {
    $script:PythonExe = (Get-Command python -ErrorAction Stop).Source
} catch {
    Show-ErrorMessage -Message 'Python が見つかりません。PATH を確認してください。'
    exit 1
}

if (-not (Test-Path $script:CompressScript)) {
    Show-ErrorMessage -Message "compress.py が見つかりません: $script:CompressScript"
    exit 1
}

function Invoke-PythonJson {
    param(
        [string[]]$Arguments
    )

    $output = & $script:PythonExe @Arguments 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    $text = $output.Trim()

    if ($exitCode -ne 0) {
        if ([string]::IsNullOrWhiteSpace($text)) {
            throw 'Python の呼び出しに失敗しました。'
        }
        throw $text
    }

    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }

    return $text | ConvertFrom-Json
}

function Get-Anchor {
    param(
        [string[]]$Sides
    )

    $anchor = [System.Windows.Forms.AnchorStyles]::None
    foreach ($side in $Sides) {
        $anchor = $anchor -bor ([System.Windows.Forms.AnchorStyles]::$side)
    }
    return $anchor
}

function Format-SizeText {
    param(
        [double]$SizeMb
    )

    if ($SizeMb -ge 1024) {
        return ('{0:N2} GB' -f ($SizeMb / 1024))
    }
    return ('{0:N2} MB' -f $SizeMb)
}

function Format-ModeText {
    param(
        [object]$Job
    )

    if ($Job.Mode -eq 'size') {
        return ('目標サイズ {0}MB' -f $Job.TargetSizeMB)
    }
    return ('目標画質 {0}' -f $Job.QualityLabel)
}

function Format-AudioText {
    param(
        [bool]$RemoveAudio
    )

    if ($RemoveAudio) {
        return '音声削除'
    }
    return '音声あり'
}

function Get-JobListText {
    param(
        [object]$Job
    )

    $parts = @(
        ('[{0}]' -f $Job.Status),
        $Job.FileName,
        (Format-ModeText -Job $Job),
        (Format-AudioText -RemoveAudio $Job.RemoveAudio)
    )

    if (-not [string]::IsNullOrWhiteSpace($Job.EstimateText)) {
        $parts += $Job.EstimateText
    }
    if (-not [string]::IsNullOrWhiteSpace($Job.ResultText)) {
        $parts += $Job.ResultText
    }

    return ($parts -join ' | ')
}

$script:Theme = @{
    Page = [System.Drawing.Color]::FromArgb(246, 248, 251)
    Card = [System.Drawing.Color]::FromArgb(255, 255, 255)
    Border = [System.Drawing.Color]::FromArgb(220, 227, 235)
    Text = [System.Drawing.Color]::FromArgb(33, 41, 54)
    Muted = [System.Drawing.Color]::FromArgb(103, 114, 128)
    Accent = [System.Drawing.Color]::FromArgb(35, 117, 240)
    AccentDark = [System.Drawing.Color]::FromArgb(24, 92, 210)
    AccentSoft = [System.Drawing.Color]::FromArgb(231, 240, 255)
    AccentSoftHover = [System.Drawing.Color]::FromArgb(220, 233, 255)
    Chip = [System.Drawing.Color]::FromArgb(242, 246, 250)
    SuccessSoft = [System.Drawing.Color]::FromArgb(232, 246, 238)
    SuccessText = [System.Drawing.Color]::FromArgb(35, 116, 74)
}

function Set-CardStyle {
    param(
        [System.Windows.Forms.Control]$Control
    )

    $Control.BackColor = $script:Theme.Card
    $Control.ForeColor = $script:Theme.Text
    $Control.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
}

function Set-SectionTitleStyle {
    param(
        [System.Windows.Forms.Label]$Label
    )

    $Label.Font = New-Object System.Drawing.Font('Yu Gothic UI Semibold', 10.5, [System.Drawing.FontStyle]::Bold)
    $Label.ForeColor = $script:Theme.Text
}

function Set-MutedLabelStyle {
    param(
        [System.Windows.Forms.Label]$Label
    )

    $Label.ForeColor = $script:Theme.Muted
}

function Set-InputStyle {
    param(
        [System.Windows.Forms.Control]$Control
    )

    $Control.BackColor = [System.Drawing.Color]::White
    $Control.ForeColor = $script:Theme.Text
    if ($Control -is [System.Windows.Forms.TextBox]) {
        $Control.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
    }
    if ($Control -is [System.Windows.Forms.ComboBox]) {
        $Control.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    }
    $Control.Font = New-Object System.Drawing.Font('Yu Gothic UI', 10)
}

function Set-ActionButtonStyle {
    param(
        [System.Windows.Forms.Button]$Button,
        [string]$Variant = 'secondary'
    )

    $Button.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $Button.FlatAppearance.BorderSize = 1
    $Button.Cursor = [System.Windows.Forms.Cursors]::Hand
    $Button.UseVisualStyleBackColor = $false
    $Button.Font = New-Object System.Drawing.Font('Yu Gothic UI Semibold', 9.5, [System.Drawing.FontStyle]::Bold)

    switch ($Variant) {
        'primary' {
            $Button.BackColor = $script:Theme.Accent
            $Button.ForeColor = [System.Drawing.Color]::White
            $Button.FlatAppearance.BorderColor = $script:Theme.Accent
            $Button.FlatAppearance.MouseOverBackColor = $script:Theme.AccentDark
            $Button.FlatAppearance.MouseDownBackColor = $script:Theme.AccentDark
        }
        'quiet' {
            $Button.BackColor = $script:Theme.Chip
            $Button.ForeColor = $script:Theme.Text
            $Button.FlatAppearance.BorderColor = $script:Theme.Border
            $Button.FlatAppearance.MouseOverBackColor = [System.Drawing.Color]::FromArgb(234, 239, 245)
            $Button.FlatAppearance.MouseDownBackColor = [System.Drawing.Color]::FromArgb(225, 231, 238)
        }
        default {
            $Button.BackColor = [System.Drawing.Color]::White
            $Button.ForeColor = $script:Theme.Text
            $Button.FlatAppearance.BorderColor = $script:Theme.Border
            $Button.FlatAppearance.MouseOverBackColor = $script:Theme.AccentSoft
            $Button.FlatAppearance.MouseDownBackColor = $script:Theme.AccentSoftHover
        }
    }
}

function Set-ModeToggleStyle {
    param(
        [System.Windows.Forms.RadioButton]$Button,
        [bool]$Active
    )

    $Button.Appearance = [System.Windows.Forms.Appearance]::Button
    $Button.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $Button.FlatAppearance.BorderSize = 1
    $Button.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $Button.Cursor = [System.Windows.Forms.Cursors]::Hand
    $Button.UseVisualStyleBackColor = $false
    $Button.Font = New-Object System.Drawing.Font('Yu Gothic UI Semibold', 9.5, [System.Drawing.FontStyle]::Bold)

    if ($Active) {
        $Button.BackColor = $script:Theme.AccentSoft
        $Button.ForeColor = $script:Theme.AccentDark
        $Button.FlatAppearance.BorderColor = $script:Theme.Accent
        $Button.FlatAppearance.MouseOverBackColor = $script:Theme.AccentSoftHover
        $Button.FlatAppearance.MouseDownBackColor = $script:Theme.AccentSoftHover
    } else {
        $Button.BackColor = $script:Theme.Chip
        $Button.ForeColor = $script:Theme.Muted
        $Button.FlatAppearance.BorderColor = $script:Theme.Border
        $Button.FlatAppearance.MouseOverBackColor = [System.Drawing.Color]::FromArgb(234, 239, 245)
        $Button.FlatAppearance.MouseDownBackColor = [System.Drawing.Color]::FromArgb(225, 231, 238)
    }
}

function Set-ChipStyle {
    param(
        [System.Windows.Forms.Label]$Label,
        [System.Drawing.Color]$BackColor,
        [System.Drawing.Color]$ForeColor
    )

    $Label.BackColor = $BackColor
    $Label.ForeColor = $ForeColor
    $Label.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $Label.Font = New-Object System.Drawing.Font('Yu Gothic UI Semibold', 9)
    $Label.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
}

try {
    $qualityProfiles = Invoke-PythonJson -Arguments @($script:CompressScript, '--list-qualities-json')
} catch {
    Show-ErrorMessage -Message $_.Exception.Message
    exit 1
}

$qualityByLabel = @{}
foreach ($profile in $qualityProfiles) {
    $qualityByLabel[[string]$profile.label] = $profile
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'mp4-comp'
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.ClientSize = New-Object System.Drawing.Size(960, 980)
$form.MinimumSize = New-Object System.Drawing.Size(960, 980)
$form.BackColor = $script:Theme.Page
$form.ForeColor = $script:Theme.Text
$form.Font = New-Object System.Drawing.Font('Yu Gothic UI', 9.5)
$form.AutoScroll = $true
$form.SuspendLayout()

$panelHeader = New-Object System.Windows.Forms.Panel
Set-CardStyle -Control $panelHeader
$panelHeader.BackColor = [System.Drawing.Color]::FromArgb(236, 245, 255)
$panelHeader.Location = New-Object System.Drawing.Point(20, 16)
$panelHeader.Size = New-Object System.Drawing.Size(920, 60)
$panelHeader.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
[void]$form.Controls.Add($panelHeader)

$headerAccent = New-Object System.Windows.Forms.Panel
$headerAccent.BackColor = $script:Theme.Accent
$headerAccent.Location = New-Object System.Drawing.Point(0, 0)
$headerAccent.Size = New-Object System.Drawing.Size(6, 60)
[void]$panelHeader.Controls.Add($headerAccent)

$labelHeaderBadge = New-Object System.Windows.Forms.Label
$labelHeaderBadge.Text = 'VIDEO COMPRESSOR'
$labelHeaderBadge.Location = New-Object System.Drawing.Point(24, 10)
$labelHeaderBadge.Size = New-Object System.Drawing.Size(180, 16)
$labelHeaderBadge.Font = New-Object System.Drawing.Font('Yu Gothic UI Semibold', 8.5, [System.Drawing.FontStyle]::Bold)
$labelHeaderBadge.ForeColor = $script:Theme.AccentDark
[void]$panelHeader.Controls.Add($labelHeaderBadge)

$labelHeaderTitle = New-Object System.Windows.Forms.Label
$labelHeaderTitle.Text = 'mp4-comp'
$labelHeaderTitle.Location = New-Object System.Drawing.Point(24, 24)
$labelHeaderTitle.Size = New-Object System.Drawing.Size(220, 24)
$labelHeaderTitle.Font = New-Object System.Drawing.Font('Yu Gothic UI Semibold', 16, [System.Drawing.FontStyle]::Bold)
$labelHeaderTitle.ForeColor = $script:Theme.Text
[void]$panelHeader.Controls.Add($labelHeaderTitle)

$labelHeaderSubtitle = New-Object System.Windows.Forms.Label
$labelHeaderSubtitle.Text = 'サイズ指定と画質プリセットの両方で、長時間ジョブをまとめて処理できます。'
$labelHeaderSubtitle.Location = New-Object System.Drawing.Point(250, 28)
$labelHeaderSubtitle.Size = New-Object System.Drawing.Size(642, 20)
$labelHeaderSubtitle.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
$labelHeaderSubtitle.ForeColor = $script:Theme.Muted
[void]$panelHeader.Controls.Add($labelHeaderSubtitle)

$labelPath = New-Object System.Windows.Forms.Label
$labelPath.Text = '入力ファイル'
$labelPath.Location = New-Object System.Drawing.Point(24, 90)
$labelPath.Size = New-Object System.Drawing.Size(160, 20)
Set-SectionTitleStyle -Label $labelPath
[void]$form.Controls.Add($labelPath)

$textPath = New-Object System.Windows.Forms.TextBox
$textPath.Location = New-Object System.Drawing.Point(20, 116)
$textPath.Size = New-Object System.Drawing.Size(776, 34)
$textPath.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
Set-InputStyle -Control $textPath
[void]$form.Controls.Add($textPath)

$buttonBrowse = New-Object System.Windows.Forms.Button
$buttonBrowse.Text = 'ファイルを選ぶ'
$buttonBrowse.Location = New-Object System.Drawing.Point(810, 116)
$buttonBrowse.Size = New-Object System.Drawing.Size(130, 34)
$buttonBrowse.Anchor = Get-Anchor -Sides @('Top', 'Right')
Set-ActionButtonStyle -Button $buttonBrowse -Variant 'secondary'
[void]$form.Controls.Add($buttonBrowse)

$groupSource = New-Object System.Windows.Forms.Panel
$groupSource.Location = New-Object System.Drawing.Point(20, 164)
$groupSource.Size = New-Object System.Drawing.Size(920, 128)
$groupSource.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
Set-CardStyle -Control $groupSource
[void]$form.Controls.Add($groupSource)

$labelSourceSection = New-Object System.Windows.Forms.Label
$labelSourceSection.Text = '元動画の状態'
$labelSourceSection.Location = New-Object System.Drawing.Point(20, 16)
$labelSourceSection.Size = New-Object System.Drawing.Size(180, 20)
Set-SectionTitleStyle -Label $labelSourceSection
[void]$groupSource.Controls.Add($labelSourceSection)

$labelCurrentTitle = New-Object System.Windows.Forms.Label
$labelCurrentTitle.Text = '現在の画質'
$labelCurrentTitle.Location = New-Object System.Drawing.Point(24, 42)
$labelCurrentTitle.Size = New-Object System.Drawing.Size(120, 20)
Set-MutedLabelStyle -Label $labelCurrentTitle
[void]$groupSource.Controls.Add($labelCurrentTitle)

$labelCurrentValue = New-Object System.Windows.Forms.Label
$labelCurrentValue.Text = 'ファイルを選択すると現在の画質を判定します。'
$labelCurrentValue.Location = New-Object System.Drawing.Point(24, 62)
$labelCurrentValue.Size = New-Object System.Drawing.Size(872, 22)
$labelCurrentValue.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
$labelCurrentValue.AutoEllipsis = $true
$labelCurrentValue.Font = New-Object System.Drawing.Font('Yu Gothic UI Semibold', 11, [System.Drawing.FontStyle]::Bold)
[void]$groupSource.Controls.Add($labelCurrentValue)

$labelDetails = New-Object System.Windows.Forms.Label
$labelDetails.Text = '長さや解像度などをここに表示します。'
$labelDetails.Location = New-Object System.Drawing.Point(24, 88)
$labelDetails.Size = New-Object System.Drawing.Size(872, 18)
$labelDetails.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
$labelDetails.AutoEllipsis = $true
Set-MutedLabelStyle -Label $labelDetails
[void]$groupSource.Controls.Add($labelDetails)

$labelSourceSize = New-Object System.Windows.Forms.Label
$labelSourceSize.Text = 'ファイルサイズ: -'
$labelSourceSize.Location = New-Object System.Drawing.Point(24, 100)
$labelSourceSize.Size = New-Object System.Drawing.Size(190, 24)
Set-ChipStyle -Label $labelSourceSize -BackColor $script:Theme.AccentSoft -ForeColor $script:Theme.AccentDark
[void]$groupSource.Controls.Add($labelSourceSize)

$labelSourceAudio = New-Object System.Windows.Forms.Label
$labelSourceAudio.Text = '音声: -'
$labelSourceAudio.Location = New-Object System.Drawing.Point(226, 100)
$labelSourceAudio.Size = New-Object System.Drawing.Size(120, 24)
$labelSourceAudio.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
Set-ChipStyle -Label $labelSourceAudio -BackColor $script:Theme.Chip -ForeColor $script:Theme.Muted
[void]$groupSource.Controls.Add($labelSourceAudio)

$groupMode = New-Object System.Windows.Forms.Panel
$groupMode.Location = New-Object System.Drawing.Point(20, 304)
$groupMode.Size = New-Object System.Drawing.Size(920, 200)
$groupMode.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
Set-CardStyle -Control $groupMode
[void]$form.Controls.Add($groupMode)

$labelModeSection = New-Object System.Windows.Forms.Label
$labelModeSection.Text = '圧縮設定'
$labelModeSection.Location = New-Object System.Drawing.Point(20, 16)
$labelModeSection.Size = New-Object System.Drawing.Size(180, 20)
Set-SectionTitleStyle -Label $labelModeSection
[void]$groupMode.Controls.Add($labelModeSection)

$radioSize = New-Object System.Windows.Forms.RadioButton
$radioSize.Text = '目標ファイルサイズで圧縮する'
$radioSize.Location = New-Object System.Drawing.Point(24, 72)
$radioSize.Size = New-Object System.Drawing.Size(246, 36)
$radioSize.Checked = $true
$radioSize.TabStop = $true
[void](Set-ModeToggleStyle -Button $radioSize -Active $true)
[void]$groupMode.Controls.Add($radioSize)

$labelOutput = New-Object System.Windows.Forms.Label
$labelOutput.Text = '出力ファイル: -'
$labelOutput.Location = New-Object System.Drawing.Point(24, 40)
$labelOutput.Size = New-Object System.Drawing.Size(872, 20)
$labelOutput.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
$labelOutput.AutoEllipsis = $true
Set-MutedLabelStyle -Label $labelOutput
[void]$groupMode.Controls.Add($labelOutput)

$labelSize = New-Object System.Windows.Forms.Label
$labelSize.Text = '目標サイズ (MB)'
$labelSize.Location = New-Object System.Drawing.Point(24, 122)
$labelSize.Size = New-Object System.Drawing.Size(140, 20)
Set-MutedLabelStyle -Label $labelSize
[void]$groupMode.Controls.Add($labelSize)

$textTargetSize = New-Object System.Windows.Forms.TextBox
$textTargetSize.Location = New-Object System.Drawing.Point(24, 146)
$textTargetSize.Size = New-Object System.Drawing.Size(120, 34)
$textTargetSize.Text = '200'
Set-InputStyle -Control $textTargetSize
[void]$groupMode.Controls.Add($textTargetSize)

$radioQuality = New-Object System.Windows.Forms.RadioButton
$radioQuality.Text = '目標画質を言葉で選んで圧縮する'
$radioQuality.Location = New-Object System.Drawing.Point(282, 72)
$radioQuality.Size = New-Object System.Drawing.Size(296, 36)
[void](Set-ModeToggleStyle -Button $radioQuality -Active $false)
[void]$groupMode.Controls.Add($radioQuality)

$labelQualityTitle = New-Object System.Windows.Forms.Label
$labelQualityTitle.Text = '目標画質'
$labelQualityTitle.Location = New-Object System.Drawing.Point(282, 122)
$labelQualityTitle.Size = New-Object System.Drawing.Size(120, 20)
Set-MutedLabelStyle -Label $labelQualityTitle
[void]$groupMode.Controls.Add($labelQualityTitle)

$comboQuality = New-Object System.Windows.Forms.ComboBox
$comboQuality.Location = New-Object System.Drawing.Point(282, 146)
$comboQuality.Size = New-Object System.Drawing.Size(240, 34)
$comboQuality.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
foreach ($profile in $qualityProfiles) {
    [void]$comboQuality.Items.Add([string]$profile.label)
}
$defaultProfile = $qualityProfiles | Where-Object { $_.key -eq 'standard' } | Select-Object -First 1
if ($null -ne $defaultProfile) {
    $comboQuality.SelectedItem = [string]$defaultProfile.label
}
Set-InputStyle -Control $comboQuality
[void]$groupMode.Controls.Add($comboQuality)

$labelQualityDescription = New-Object System.Windows.Forms.Label
$labelQualityDescription.Location = New-Object System.Drawing.Point(536, 148)
$labelQualityDescription.Size = New-Object System.Drawing.Size(360, 34)
$labelQualityDescription.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
Set-MutedLabelStyle -Label $labelQualityDescription
[void]$groupMode.Controls.Add($labelQualityDescription)

$checkRemoveAudio = New-Object System.Windows.Forms.CheckBox
$checkRemoveAudio.Text = '音声を削除する'
$checkRemoveAudio.Location = New-Object System.Drawing.Point(24, 170)
$checkRemoveAudio.Size = New-Object System.Drawing.Size(170, 24)
$checkRemoveAudio.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$checkRemoveAudio.ForeColor = $script:Theme.Text
[void]$groupMode.Controls.Add($checkRemoveAudio)

$labelEstimate = New-Object System.Windows.Forms.Label
$labelEstimate.Text = '目安ファイルサイズ: -'
$labelEstimate.Location = New-Object System.Drawing.Point(282, 170)
$labelEstimate.Size = New-Object System.Drawing.Size(614, 22)
$labelEstimate.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
$labelEstimate.Font = New-Object System.Drawing.Font('Yu Gothic UI Semibold', 9.5, [System.Drawing.FontStyle]::Bold)
[void]$groupMode.Controls.Add($labelEstimate)

$groupQueue = New-Object System.Windows.Forms.Panel
$groupQueue.Location = New-Object System.Drawing.Point(20, 516)
$groupQueue.Size = New-Object System.Drawing.Size(920, 200)
$groupQueue.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
Set-CardStyle -Control $groupQueue
[void]$form.Controls.Add($groupQueue)

$labelQueueSection = New-Object System.Windows.Forms.Label
$labelQueueSection.Text = '予約キュー'
$labelQueueSection.Location = New-Object System.Drawing.Point(20, 16)
$labelQueueSection.Size = New-Object System.Drawing.Size(180, 20)
Set-SectionTitleStyle -Label $labelQueueSection
[void]$groupQueue.Controls.Add($labelQueueSection)

$labelQueueSummary = New-Object System.Windows.Forms.Label
$labelQueueSummary.Text = '待機 0 / 実行中 0 / 完了 0 / 失敗 0'
$labelQueueSummary.Location = New-Object System.Drawing.Point(620, 16)
$labelQueueSummary.Size = New-Object System.Drawing.Size(276, 20)
$labelQueueSummary.TextAlign = [System.Drawing.ContentAlignment]::MiddleRight
$labelQueueSummary.Anchor = Get-Anchor -Sides @('Top', 'Right')
Set-MutedLabelStyle -Label $labelQueueSummary
[void]$groupQueue.Controls.Add($labelQueueSummary)

$listQueue = New-Object System.Windows.Forms.ListBox
$listQueue.Location = New-Object System.Drawing.Point(24, 50)
$listQueue.Size = New-Object System.Drawing.Size(688, 118)
$listQueue.Anchor = Get-Anchor -Sides @('Top', 'Bottom', 'Left', 'Right')
$listQueue.HorizontalScrollbar = $true
$listQueue.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$listQueue.BackColor = [System.Drawing.Color]::White
$listQueue.ForeColor = $script:Theme.Text
$listQueue.Font = New-Object System.Drawing.Font('Yu Gothic UI', 9.5)
$listQueue.IntegralHeight = $false
[void]$groupQueue.Controls.Add($listQueue)

$buttonStartCurrent = New-Object System.Windows.Forms.Button
$buttonStartCurrent.Text = 'この設定で開始'
$buttonStartCurrent.Location = New-Object System.Drawing.Point(726, 42)
$buttonStartCurrent.Size = New-Object System.Drawing.Size(170, 26)
$buttonStartCurrent.Anchor = Get-Anchor -Sides @('Top', 'Right')
Set-ActionButtonStyle -Button $buttonStartCurrent -Variant 'primary'
[void]$groupQueue.Controls.Add($buttonStartCurrent)

$buttonAddQueue = New-Object System.Windows.Forms.Button
$buttonAddQueue.Text = 'この設定を予約'
$buttonAddQueue.Location = New-Object System.Drawing.Point(726, 74)
$buttonAddQueue.Size = New-Object System.Drawing.Size(170, 26)
$buttonAddQueue.Anchor = Get-Anchor -Sides @('Top', 'Right')
Set-ActionButtonStyle -Button $buttonAddQueue -Variant 'secondary'
[void]$groupQueue.Controls.Add($buttonAddQueue)

$buttonStartQueue = New-Object System.Windows.Forms.Button
$buttonStartQueue.Text = '待機ジョブ開始'
$buttonStartQueue.Location = New-Object System.Drawing.Point(726, 106)
$buttonStartQueue.Size = New-Object System.Drawing.Size(170, 26)
$buttonStartQueue.Anchor = Get-Anchor -Sides @('Top', 'Right')
Set-ActionButtonStyle -Button $buttonStartQueue -Variant 'secondary'
[void]$groupQueue.Controls.Add($buttonStartQueue)

$buttonRemoveSelected = New-Object System.Windows.Forms.Button
$buttonRemoveSelected.Text = '選択行削除'
$buttonRemoveSelected.Location = New-Object System.Drawing.Point(726, 138)
$buttonRemoveSelected.Size = New-Object System.Drawing.Size(170, 26)
$buttonRemoveSelected.Anchor = Get-Anchor -Sides @('Top', 'Right')
Set-ActionButtonStyle -Button $buttonRemoveSelected -Variant 'quiet'
[void]$groupQueue.Controls.Add($buttonRemoveSelected)

$buttonClearFinished = New-Object System.Windows.Forms.Button
$buttonClearFinished.Text = '完了/失敗を削除'
$buttonClearFinished.Location = New-Object System.Drawing.Point(726, 170)
$buttonClearFinished.Size = New-Object System.Drawing.Size(170, 26)
$buttonClearFinished.Anchor = Get-Anchor -Sides @('Top', 'Right')
Set-ActionButtonStyle -Button $buttonClearFinished -Variant 'quiet'
[void]$groupQueue.Controls.Add($buttonClearFinished)

$groupProgress = New-Object System.Windows.Forms.Panel
$groupProgress.Location = New-Object System.Drawing.Point(20, 724)
$groupProgress.Size = New-Object System.Drawing.Size(920, 110)
$groupProgress.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
Set-CardStyle -Control $groupProgress
[void]$form.Controls.Add($groupProgress)

$labelProgressSection = New-Object System.Windows.Forms.Label
$labelProgressSection.Text = '進捗'
$labelProgressSection.Location = New-Object System.Drawing.Point(20, 16)
$labelProgressSection.Size = New-Object System.Drawing.Size(180, 20)
Set-SectionTitleStyle -Label $labelProgressSection
[void]$groupProgress.Controls.Add($labelProgressSection)

$labelCurrentJob = New-Object System.Windows.Forms.Label
$labelCurrentJob.Text = '実行中ジョブ: なし'
$labelCurrentJob.Location = New-Object System.Drawing.Point(24, 38)
$labelCurrentJob.Size = New-Object System.Drawing.Size(872, 20)
$labelCurrentJob.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
$labelCurrentJob.AutoEllipsis = $true
[void]$groupProgress.Controls.Add($labelCurrentJob)

$labelProgressStage = New-Object System.Windows.Forms.Label
$labelProgressStage.Text = 'エンコード段階: 待機中'
$labelProgressStage.Location = New-Object System.Drawing.Point(24, 60)
$labelProgressStage.Size = New-Object System.Drawing.Size(300, 18)
Set-MutedLabelStyle -Label $labelProgressStage
[void]$groupProgress.Controls.Add($labelProgressStage)

$labelProgressTime = New-Object System.Windows.Forms.Label
$labelProgressTime.Text = '- / -'
$labelProgressTime.Location = New-Object System.Drawing.Point(618, 60)
$labelProgressTime.Size = New-Object System.Drawing.Size(278, 18)
$labelProgressTime.TextAlign = [System.Drawing.ContentAlignment]::MiddleRight
$labelProgressTime.Anchor = Get-Anchor -Sides @('Top', 'Right')
Set-MutedLabelStyle -Label $labelProgressTime
[void]$groupProgress.Controls.Add($labelProgressTime)

$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Location = New-Object System.Drawing.Point(24, 82)
$progressBar.Size = New-Object System.Drawing.Size(742, 14)
$progressBar.Style = [System.Windows.Forms.ProgressBarStyle]::Continuous
$progressBar.Anchor = Get-Anchor -Sides @('Top', 'Left', 'Right')
$progressBar.MarqueeAnimationSpeed = 25
[void]$groupProgress.Controls.Add($progressBar)

$labelProgressText = New-Object System.Windows.Forms.Label
$labelProgressText.Text = '0%'
$labelProgressText.Location = New-Object System.Drawing.Point(780, 72)
$labelProgressText.Size = New-Object System.Drawing.Size(116, 28)
$labelProgressText.Anchor = Get-Anchor -Sides @('Top', 'Right')
$labelProgressText.TextAlign = [System.Drawing.ContentAlignment]::MiddleRight
$labelProgressText.Font = New-Object System.Drawing.Font('Yu Gothic UI Semibold', 14, [System.Drawing.FontStyle]::Bold)
[void]$groupProgress.Controls.Add($labelProgressText)

$groupStatus = New-Object System.Windows.Forms.Panel
$groupStatus.Location = New-Object System.Drawing.Point(20, 846)
$groupStatus.Size = New-Object System.Drawing.Size(920, 124)
$groupStatus.Anchor = Get-Anchor -Sides @('Top', 'Bottom', 'Left', 'Right')
Set-CardStyle -Control $groupStatus
[void]$form.Controls.Add($groupStatus)

$labelStatusSection = New-Object System.Windows.Forms.Label
$labelStatusSection.Text = 'ステータス'
$labelStatusSection.Location = New-Object System.Drawing.Point(20, 16)
$labelStatusSection.Size = New-Object System.Drawing.Size(180, 20)
Set-SectionTitleStyle -Label $labelStatusSection
[void]$groupStatus.Controls.Add($labelStatusSection)

$textStatus = New-Object System.Windows.Forms.TextBox
$textStatus.Location = New-Object System.Drawing.Point(24, 46)
$textStatus.Size = New-Object System.Drawing.Size(872, 58)
$textStatus.Multiline = $true
$textStatus.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
$textStatus.ReadOnly = $true
$textStatus.Anchor = Get-Anchor -Sides @('Top', 'Bottom', 'Left', 'Right')
$textStatus.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$textStatus.BackColor = [System.Drawing.Color]::FromArgb(250, 252, 255)
$textStatus.ForeColor = $script:Theme.Text
$textStatus.Font = New-Object System.Drawing.Font('Yu Gothic UI', 9)
$textStatus.Text = "準備完了です。`r`n"
[void]$groupStatus.Controls.Add($textStatus)

$form.ResumeLayout($false)

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 300

function Add-Log {
    param(
        [string]$Message
    )

    if ([string]::IsNullOrWhiteSpace($Message)) {
        return
    }

    $textStatus.AppendText($Message + [Environment]::NewLine)
    $textStatus.SelectionStart = $textStatus.TextLength
    $textStatus.ScrollToCaret()
}

function Get-ProgressTimeText {
    param(
        [string]$CurrentText,
        [string]$TotalText
    )

    if ([string]::IsNullOrWhiteSpace($CurrentText) -and [string]::IsNullOrWhiteSpace($TotalText)) {
        return '- / -'
    }

    if ([string]::IsNullOrWhiteSpace($CurrentText)) {
        return ('0:00 / {0}' -f $TotalText)
    }

    if ([string]::IsNullOrWhiteSpace($TotalText)) {
        return ('{0} / -' -f $CurrentText)
    }

    return ('{0} / {1}' -f $CurrentText, $TotalText)
}

function Set-ProgressState {
    param(
        [int]$Percent,
        [string]$Label,
        [bool]$Indeterminate,
        [string]$CurrentText = '',
        [string]$TotalText = ''
    )

    if (-not [string]::IsNullOrWhiteSpace($CurrentText)) {
        $script:LastProgressCurrentText = $CurrentText
    }
    if (-not [string]::IsNullOrWhiteSpace($TotalText)) {
        $script:LastProgressTotalText = $TotalText
    }

    if ($Indeterminate) {
        $progressBar.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
        $labelProgressStage.Text = ('エンコード段階: {0}' -f $Label)
        $labelProgressTime.Text = Get-ProgressTimeText -CurrentText $script:LastProgressCurrentText -TotalText $script:LastProgressTotalText
        $labelProgressText.Text = '...'
        return
    }

    if ($progressBar.Style -ne [System.Windows.Forms.ProgressBarStyle]::Continuous) {
        $progressBar.Style = [System.Windows.Forms.ProgressBarStyle]::Continuous
    }

    $clamped = [Math]::Max(0, [Math]::Min(100, $Percent))
    $progressBar.Value = $clamped
    $labelProgressStage.Text = if ([string]::IsNullOrWhiteSpace($Label)) { 'エンコード段階: 実行中' } else { ('エンコード段階: {0}' -f $Label) }
    $labelProgressTime.Text = Get-ProgressTimeText -CurrentText $script:LastProgressCurrentText -TotalText $script:LastProgressTotalText
    $labelProgressText.Text = ('{0}%' -f $clamped)
}

function Reset-ProgressState {
    $script:LastProgressCurrentText = ''
    $script:LastProgressTotalText = ''
    $progressBar.Style = [System.Windows.Forms.ProgressBarStyle]::Continuous
    $progressBar.Value = 0
    $labelProgressStage.Text = 'エンコード段階: 待機中'
    $labelProgressTime.Text = '- / -'
    $labelProgressText.Text = '0%'
    $labelCurrentJob.Text = '実行中ジョブ: なし'
}

function Get-SelectedQualityProfile {
    $selectedLabel = [string]$comboQuality.SelectedItem
    if ([string]::IsNullOrWhiteSpace($selectedLabel)) {
        return $null
    }
    return $qualityByLabel[$selectedLabel]
}

function Update-QualityDescription {
    $selectedProfile = Get-SelectedQualityProfile
    if ($null -eq $selectedProfile) {
        $labelQualityDescription.Text = ''
        return
    }
    $labelQualityDescription.Text = [string]$selectedProfile.description
}

function Get-CurrentOutputName {
    $path = $textPath.Text.Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($path)) {
        return '-'
    }

    try {
        $fullPath = [System.IO.Path]::GetFullPath($path)
        $directory = [System.IO.Path]::GetDirectoryName($fullPath)
        $name = [System.IO.Path]::GetFileNameWithoutExtension($fullPath)
        $extension = [System.IO.Path]::GetExtension($fullPath)
        $noAudioSuffix = ''
        if ($checkRemoveAudio.Checked) {
            $noAudioSuffix = '_noaudio'
        }

        if ($radioSize.Checked) {
            $outputName = '{0}_compressed{1}{2}' -f $name, $noAudioSuffix, $extension
        } else {
            $selectedProfile = Get-SelectedQualityProfile
            if ($null -eq $selectedProfile) {
                return '-'
            }
            $outputName = '{0}_quality_{1}{2}{3}' -f $name, [string]$selectedProfile.key, $noAudioSuffix, $extension
        }

        return (Join-Path $directory $outputName)
    } catch {
        return '-'
    }
}

function Update-OutputHint {
    $labelOutput.Text = ('出力ファイル: {0}' -f (Get-CurrentOutputName))
}

function Update-EstimateDisplay {
    if ($null -eq $script:CurrentProbeData) {
        $labelEstimate.Text = '目安ファイルサイズ: -'
        Update-OutputHint
        return
    }

    if ($radioSize.Checked) {
        $targetText = $textTargetSize.Text.Trim()
        if ([string]::IsNullOrWhiteSpace($targetText)) {
            $labelEstimate.Text = '予定出力サイズ: -'
        } else {
            $labelEstimate.Text = ('予定出力サイズ: 約 {0} MB' -f $targetText)
        }
        Update-OutputHint
        return
    }

    $selectedProfile = Get-SelectedQualityProfile
    if ($null -eq $selectedProfile) {
        $labelEstimate.Text = '目安ファイルサイズ: -'
        Update-OutputHint
        return
    }

    $estimate = $script:CurrentProbeData.estimated_sizes_mb.([string]$selectedProfile.key)
    if ($null -eq $estimate) {
        $labelEstimate.Text = '目安ファイルサイズ: -'
        Update-OutputHint
        return
    }

    if ($checkRemoveAudio.Checked) {
        $estimateMb = [double]$estimate.without_audio_mb
    } else {
        $estimateMb = [double]$estimate.with_audio_mb
    }

    $labelEstimate.Text = ('目安ファイルサイズ: 約 {0}' -f (Format-SizeText -SizeMb $estimateMb))
    Update-OutputHint
}

function Refresh-JobList {
    $selectedIndex = $listQueue.SelectedIndex
    $listQueue.BeginUpdate()
    $listQueue.Items.Clear()
    foreach ($job in $script:Jobs) {
        [void]$listQueue.Items.Add((Get-JobListText -Job $job))
    }
    if ($selectedIndex -ge 0 -and $selectedIndex -lt $listQueue.Items.Count) {
        $listQueue.SelectedIndex = $selectedIndex
    }
    $listQueue.EndUpdate()
    $labelQueueSummary.Text = Get-QueueSummaryText
}

function Get-QueueSummaryText {
    $waiting = @($script:Jobs | Where-Object { $_.Status -eq '待機' }).Count
    $running = @($script:Jobs | Where-Object { $_.Status -eq '実行中' }).Count
    $done = @($script:Jobs | Where-Object { $_.Status -eq '完了' }).Count
    $failed = @($script:Jobs | Where-Object { $_.Status -eq '失敗' }).Count
    return ('待機 {0} / 実行中 {1} / 完了 {2} / 失敗 {3}' -f $waiting, $running, $done, $failed)
}

function Add-QueueSummaryLog {
    Add-Log ('キュー状況: {0}' -f (Get-QueueSummaryText))
}

function Ensure-ProbeData {
    $inputPath = $textPath.Text.Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($inputPath)) {
        Show-ErrorMessage -Message '圧縮する MP4 ファイルを選択してください。' -Title '入力不足'
        return $false
    }

    if (-not (Test-Path $inputPath)) {
        Show-ErrorMessage -Message '指定されたファイルが見つかりません。' -Title '入力不足'
        return $false
    }

    $fullPath = [System.IO.Path]::GetFullPath($inputPath)
    if ($script:CurrentProbePath -ne $fullPath) {
        Update-SourceInfo -PathToFile $inputPath -ShowMessage $true
    }

    return $null -ne $script:CurrentProbeData
}

function Update-SourceInfo {
    param(
        [string]$PathToFile,
        [bool]$ShowMessage
    )

    $cleanPath = $PathToFile.Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($cleanPath)) {
        $script:CurrentProbeData = $null
        $script:CurrentProbePath = $null
        $labelCurrentValue.Text = 'ファイルを選択すると現在の画質を判定します。'
        $labelDetails.Text = '長さや解像度などをここに表示します。'
        $labelSourceSize.Text = 'ファイルサイズ: -'
        $labelSourceAudio.Text = '音声: -'
        Set-ChipStyle -Label $labelSourceAudio -BackColor $script:Theme.Chip -ForeColor $script:Theme.Muted
        Update-EstimateDisplay
        return
    }

    try {
        $probeData = Invoke-PythonJson -Arguments @($script:CompressScript, $cleanPath, '--probe-json')
        $script:CurrentProbeData = $probeData
        $script:CurrentProbePath = [System.IO.Path]::GetFullPath($cleanPath)
        $labelCurrentValue.Text = '{0} - {1}' -f [string]$probeData.current_quality.label, [string]$probeData.current_quality.description
        $labelDetails.Text = [string]$probeData.video_summary
        $labelSourceSize.Text = ('ファイルサイズ: {0}' -f (Format-SizeText -SizeMb ([double]$probeData.video_info.source_size_mb)))
        if ([bool]$probeData.video_info.has_audio) {
            $labelSourceAudio.Text = '音声: あり'
            Set-ChipStyle -Label $labelSourceAudio -BackColor $script:Theme.SuccessSoft -ForeColor $script:Theme.SuccessText
        } else {
            $labelSourceAudio.Text = '音声: なし'
            Set-ChipStyle -Label $labelSourceAudio -BackColor $script:Theme.Chip -ForeColor $script:Theme.Muted
        }
        Add-Log ('解析完了: {0}' -f [System.IO.Path]::GetFileName($cleanPath))
    } catch {
        $script:CurrentProbeData = $null
        $script:CurrentProbePath = $null
        $labelCurrentValue.Text = '解析に失敗しました。'
        $labelDetails.Text = $_.Exception.Message
        $labelSourceSize.Text = 'ファイルサイズ: -'
        $labelSourceAudio.Text = '音声: -'
        Set-ChipStyle -Label $labelSourceAudio -BackColor $script:Theme.Chip -ForeColor $script:Theme.Muted
        if ($ShowMessage) {
            Show-ErrorMessage -Message $_.Exception.Message -Title '解析エラー'
        }
    }

    Update-EstimateDisplay
}

function Build-CurrentJob {
    if (-not (Ensure-ProbeData)) {
        return $null
    }

    $inputPath = [System.IO.Path]::GetFullPath($textPath.Text.Trim().Trim('"'))
    $removeAudio = [bool]$checkRemoveAudio.Checked
    $job = [PSCustomObject]@{
        Id = [Guid]::NewGuid().ToString()
        FilePath = $inputPath
        FileName = [System.IO.Path]::GetFileName($inputPath)
        Mode = if ($radioSize.Checked) { 'size' } else { 'quality' }
        TargetSizeMB = $null
        QualityKey = $null
        QualityLabel = $null
        RemoveAudio = $removeAudio
        Status = '待機'
        EstimateText = ''
        ResultText = ''
        OutputHint = Get-CurrentOutputName
        DurationText = [string]$script:CurrentProbeData.video_info.duration_text
    }

    if ($job.Mode -eq 'size') {
        try {
            $targetSize = [int]$textTargetSize.Text
        } catch {
            Show-ErrorMessage -Message '目標サイズは整数で入力してください。' -Title '入力不足'
            return $null
        }

        if ($targetSize -le 0) {
            Show-ErrorMessage -Message '目標サイズは 1MB 以上で指定してください。' -Title '入力不足'
            return $null
        }

        $job.TargetSizeMB = $targetSize
        $job.EstimateText = ('予定 {0} MB' -f $targetSize)
        return $job
    }

    $selectedProfile = Get-SelectedQualityProfile
    if ($null -eq $selectedProfile) {
        Show-ErrorMessage -Message '目標画質を選択してください。' -Title '入力不足'
        return $null
    }

    $job.QualityKey = [string]$selectedProfile.key
    $job.QualityLabel = [string]$selectedProfile.label

    $estimate = $script:CurrentProbeData.estimated_sizes_mb.($job.QualityKey)
    if ($null -ne $estimate) {
        if ($removeAudio) {
            $job.EstimateText = ('目安 {0}' -f (Format-SizeText -SizeMb ([double]$estimate.without_audio_mb)))
        } else {
            $job.EstimateText = ('目安 {0}' -f (Format-SizeText -SizeMb ([double]$estimate.with_audio_mb)))
        }
    }

    return $job
}

function Add-JobToQueue {
    param(
        [object]$Job
    )

    if ($null -eq $Job) {
        return
    }

    [void]$script:Jobs.Add($Job)
    Refresh-JobList
    Add-Log ('予約追加: {0}' -f (Get-JobListText -Job $Job))
    Add-QueueSummaryLog
}

function Get-FirstWaitingJob {
    foreach ($job in $script:Jobs) {
        if ($job.Status -eq '待機') {
            return $job
        }
    }
    return $null
}

function Get-JobOrderText {
    param(
        [object]$Job
    )

    $totalCount = [Math]::Max(1, $script:Jobs.Count)
    $position = 1
    for ($index = 0; $index -lt $script:Jobs.Count; $index++) {
        if ($script:Jobs[$index].Id -eq $Job.Id) {
            $position = $index + 1
            break
        }
    }
    return ('{0}/{1}' -f $position, $totalCount)
}

function Reset-ProcessFiles {
    foreach ($path in @($script:CurrentStdOutFile, $script:CurrentStdErrFile)) {
        if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path $path)) {
            try {
                Remove-Item -Force $path -ErrorAction SilentlyContinue
            } catch {
            }
        }
    }

    $script:CurrentStdOutFile = $null
    $script:CurrentStdErrFile = $null
    $script:LastStdOutLength = 0
    $script:LastStdErrLength = 0
    $script:LastBackendResult = $null
}

function Append-ProcessLogFile {
    param(
        [string]$Path,
        [ref]$LastLength
    )

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path)) {
        return
    }

    try {
        $content = [System.IO.File]::ReadAllText($Path)
    } catch {
        return
    }

    if ($content.Length -lt $LastLength.Value) {
        $LastLength.Value = 0
    }

    if ($content.Length -le $LastLength.Value) {
        return
    }

    $newText = $content.Substring($LastLength.Value)
    $LastLength.Value = $content.Length
    foreach ($line in ($newText -split "(`r`n|`n|`r)")) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        if ($line.StartsWith($script:EventPrefix)) {
            Handle-BackendEvent -Line $line
            continue
        }
        Add-Log $line
    }
}

function Handle-BackendEvent {
    param(
        [string]$Line
    )

    try {
        $event = $Line.Substring($script:EventPrefix.Length) | ConvertFrom-Json
    } catch {
        return
    }

    if ($event.type -eq 'progress') {
        $percent = [int][Math]::Round([double]$event.percent)
        $label = [string]$event.label
        $currentText = [string]$event.current_text
        $totalText = [string]$event.total_text
        Set-ProgressState -Percent $percent -Label $label -Indeterminate $false -CurrentText $currentText -TotalText $totalText
        return
    }

    if ($event.type -eq 'result') {
        $script:LastBackendResult = $event
    }
}

function Start-CompressionProcess {
    param(
        [object]$Job
    )

    Reset-ProcessFiles
    $script:CurrentStdOutFile = [System.IO.Path]::GetTempFileName()
    $script:CurrentStdErrFile = [System.IO.Path]::GetTempFileName()

    $arguments = @($script:CompressScript, $Job.FilePath)
    if ($Job.Mode -eq 'size') {
        $arguments += [string]$Job.TargetSizeMB
    } else {
        $arguments += @('--mode', 'quality', '--quality', [string]$Job.QualityKey)
    }
    if ($Job.RemoveAudio) {
        $arguments += '--no-audio'
    }

    $script:CurrentProcess = Start-Process `
        -FilePath $script:PythonExe `
        -ArgumentList $arguments `
        -WorkingDirectory $script:ScriptDir `
        -RedirectStandardOutput $script:CurrentStdOutFile `
        -RedirectStandardError $script:CurrentStdErrFile `
        -PassThru `
        -WindowStyle Hidden

    if ($null -eq $script:CurrentProcess) {
        Reset-ProcessFiles
        throw '圧縮プロセスを開始できませんでした。'
    }

    $script:CurrentJob = $Job
    $Job.Status = '実行中'
    $Job.ResultText = ''
    Refresh-JobList
    $labelCurrentJob.Text = ('実行中ジョブ {0}: {1} / {2}' -f (Get-JobOrderText -Job $Job), $Job.FileName, (Format-ModeText -Job $Job))
    Set-ProgressState -Percent 0 -Label '準備中...' -Indeterminate $true -CurrentText '0:00' -TotalText $Job.DurationText
    Add-Log ('ジョブ開始: {0}' -f (Get-JobListText -Job $Job))
    Add-QueueSummaryLog
    $timer.Start()
}

function Try-StartNextJob {
    if ($null -ne $script:CurrentJob) {
        return
    }

    $nextJob = Get-FirstWaitingJob
    if ($null -eq $nextJob) {
        Reset-ProgressState
        Add-Log '待機ジョブはありません。'
        return
    }

    try {
        Start-CompressionProcess -Job $nextJob
    } catch {
        $nextJob.Status = '失敗'
        $nextJob.ResultText = $_.Exception.Message
        Refresh-JobList
        Reset-ProgressState
        Add-Log ('ジョブ開始失敗: {0}' -f $_.Exception.Message)
    }
}

$timer.Add_Tick({
    Append-ProcessLogFile -Path $script:CurrentStdOutFile -LastLength ([ref]$script:LastStdOutLength)
    Append-ProcessLogFile -Path $script:CurrentStdErrFile -LastLength ([ref]$script:LastStdErrLength)

    if ($null -eq $script:CurrentProcess) {
        return
    }

    if (-not $script:CurrentProcess.HasExited) {
        return
    }

    $timer.Stop()
    try {
        $script:CurrentProcess.WaitForExit()
    } catch {
    }

    Append-ProcessLogFile -Path $script:CurrentStdOutFile -LastLength ([ref]$script:LastStdOutLength)
    Append-ProcessLogFile -Path $script:CurrentStdErrFile -LastLength ([ref]$script:LastStdErrLength)

    $exitCode = $null
    try {
        $exitCode = [int]$script:CurrentProcess.ExitCode
    } catch {
        $exitCode = $null
    }

    $script:CurrentProcess.Dispose()
    $script:CurrentProcess = $null

    $job = $script:CurrentJob
    $script:CurrentJob = $null

    $wasSuccessful = $false
    if ($null -ne $exitCode -and $exitCode -eq 0) {
        $wasSuccessful = $true
    } elseif ($null -ne $script:LastBackendResult) {
        $resultPath = [string]$script:LastBackendResult.output_file
        if (-not [string]::IsNullOrWhiteSpace($resultPath) -and (Test-Path $resultPath)) {
            $wasSuccessful = $true
            Add-Log '終了コードが取れなかったため、完了イベントを優先して成功判定しました。'
        }
    }

    if ($wasSuccessful) {
        $job.Status = '完了'
        if ($null -ne $script:LastBackendResult) {
            $job.ResultText = ('出力 {0}' -f (Format-SizeText -SizeMb ([double]$script:LastBackendResult.final_size_mb)))
        } else {
            $job.ResultText = '完了'
        }
        Set-ProgressState -Percent 100 -Label '完了' -Indeterminate $false -CurrentText $job.DurationText -TotalText $job.DurationText
        Add-Log ('ジョブ完了: {0}' -f (Get-JobListText -Job $job))
    } else {
        $job.Status = '失敗'
        if ($null -eq $exitCode) {
            $job.ResultText = '終了コード不明'
            Add-Log 'ジョブ失敗: 終了コードを取得できませんでした。'
        } else {
            $job.ResultText = ('終了コード {0}' -f $exitCode)
            Add-Log ('ジョブ失敗: 終了コード {0}' -f $exitCode)
        }
        Set-ProgressState -Percent 0 -Label '失敗' -Indeterminate $false -CurrentText $script:LastProgressCurrentText -TotalText $script:LastProgressTotalText
    }

    Refresh-JobList
    Add-QueueSummaryLog
    Reset-ProcessFiles

    $remainingJob = Get-FirstWaitingJob
    if ($null -ne $remainingJob) {
        Try-StartNextJob
    } else {
        Reset-ProgressState
        Add-Log 'キュー処理が完了しました。'
    }
})

$buttonBrowse.Add_Click({
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Filter = 'MP4 files (*.mp4)|*.mp4|All files (*.*)|*.*'
    $dialog.Title = 'MP4ファイルを選択'
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        $textPath.Text = $dialog.FileName
        Update-SourceInfo -PathToFile $dialog.FileName -ShowMessage $true
    }
    $dialog.Dispose()
})

$textPath.Add_Leave({
    Update-SourceInfo -PathToFile $textPath.Text -ShowMessage $false
})

$radioSize.Add_CheckedChanged({
    Update-ModeControls
    Update-EstimateDisplay
})

$radioQuality.Add_CheckedChanged({
    Update-ModeControls
    Update-EstimateDisplay
})

$comboQuality.Add_SelectedIndexChanged({
    Update-QualityDescription
    Update-EstimateDisplay
})

$checkRemoveAudio.Add_CheckedChanged({
    Update-EstimateDisplay
})

$textTargetSize.Add_TextChanged({
    if ($radioSize.Checked) {
        Update-EstimateDisplay
    }
})

$buttonAddQueue.Add_Click({
    $job = Build-CurrentJob
    if ($null -eq $job) {
        return
    }
    Add-JobToQueue -Job $job
})

$buttonStartCurrent.Add_Click({
    $job = Build-CurrentJob
    if ($null -eq $job) {
        return
    }

    Add-JobToQueue -Job $job
    if ($null -eq $script:CurrentJob) {
        Try-StartNextJob
        return
    }

    Add-Log '現在ジョブ実行中のため、待機列に追加しました。'
})

$buttonStartQueue.Add_Click({
    if ($null -ne $script:CurrentJob) {
        Add-Log 'すでにジョブを実行中です。'
        return
    }
    Try-StartNextJob
})

$buttonRemoveSelected.Add_Click({
    $index = $listQueue.SelectedIndex
    if ($index -lt 0 -or $index -ge $script:Jobs.Count) {
        return
    }

    $job = $script:Jobs[$index]
    if ($job.Status -eq '実行中') {
        Show-ErrorMessage -Message '実行中のジョブは削除できません。' -Title '削除不可'
        return
    }

    $null = $script:Jobs.RemoveAt($index)
    Refresh-JobList
    Add-Log ('ジョブ削除: {0}' -f $job.FileName)
    Add-QueueSummaryLog
})

$buttonClearFinished.Add_Click({
    for ($index = $script:Jobs.Count - 1; $index -ge 0; $index--) {
        $job = $script:Jobs[$index]
        if ($job.Status -in @('完了', '失敗')) {
            $null = $script:Jobs.RemoveAt($index)
        }
    }
    Refresh-JobList
    Add-Log '完了/失敗ジョブを一覧から削除しました。'
    Add-QueueSummaryLog
})

$form.Add_FormClosing({
    if ($null -eq $script:CurrentProcess -or $script:CurrentProcess.HasExited) {
        return
    }

    $result = [System.Windows.Forms.MessageBox]::Show(
        $form,
        '圧縮中です。停止して閉じますか。',
        '確認',
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )

    if ($result -ne [System.Windows.Forms.DialogResult]::Yes) {
        $_.Cancel = $true
        return
    }

    try {
        $script:CurrentProcess.Kill()
    } catch {
    }
})

function Update-ModeControls {
    Set-ModeToggleStyle -Button $radioSize -Active $radioSize.Checked
    Set-ModeToggleStyle -Button $radioQuality -Active $radioQuality.Checked

    if ($radioSize.Checked) {
        $textTargetSize.Enabled = $true
        $comboQuality.Enabled = $false
        $labelSize.ForeColor = $script:Theme.Text
        $labelQualityTitle.ForeColor = $script:Theme.Muted
        $labelQualityDescription.ForeColor = $script:Theme.Muted
    } else {
        $textTargetSize.Enabled = $false
        $comboQuality.Enabled = $true
        $labelSize.ForeColor = $script:Theme.Muted
        $labelQualityTitle.ForeColor = $script:Theme.Text
        $labelQualityDescription.ForeColor = $script:Theme.Muted
    }
}

Update-QualityDescription
Update-ModeControls
Update-EstimateDisplay
Reset-ProgressState
Refresh-JobList
[void]$form.ShowDialog()
