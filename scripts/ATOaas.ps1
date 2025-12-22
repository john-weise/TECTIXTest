param( 
    [string]$SystemID, 
    [string]$dataPath, 
    [string]$ChecklistPath, 
    [string]$OutputJson,
    [string]$ResultsJson )


$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::UTF8
[Console]::Out.Flush()

Write-Host "Script started..."

$DemoAssets = '.\Notionalassets' 

#start the clock
$StartTime = Get-Date

#Clear the screen and display company logo


Write-Host ""
Write-Host ""
$logoart = @"                                                                  
           #####                                                          
          #######                                                         
 **       #######                                                         
***********##### *******                                                  
 ***********************                                                  
       ===************                                                    
    ======== ****     **********    *           *********  ****       ****
   ====        ***   ************ ****        ************  *****   ***** 
 ===            **   ***      ********        ****           **********   
==              **   *****************        ***********      *******    
               **    ************ ****        ****            *********   
              *      ***          *********** ************  *****  ****** 
                     ***          *********** ***********  *****     *****
                                                                                                                                                                                                                   
"@
Write-Host -ForegroundColor Green $logoart
Write-Host ""
Write-Host -ForegroundColor Green "ATO as a Service NCS Demo"
Write-Host -ForegroundColor Green "Version: 2.0 - 16AUGUST2025"
Write-Host -ForegroundColor Green "PLEX Solutions LLC"
Write-Host -ForegroundColor Green "John Weise and Richard Trapp"
Write-Host ""
Write-Host ""
Write-Host -ForegroundColor Cyan "System ID: $SystemID"
Write-Host -ForegroundColor Cyan "data Report Path: $dataPath"
Write-Host -ForegroundColor Cyan "Checklist Path: $ChecklistPath"

$ErrorActionPreference = "SilentlyContinue"

Start-Sleep -Seconds 10

# initial check of connection to the API
$connectresult = Get-Content (join-path $DemoAssets "InitialTest.json") | ConvertFrom-Json
$connectcode = $connectresult.meta | Select-Object -ExpandProperty code


if ($connectcode -eq "200"){

    Write-Host ""
    Write-Host -ForegroundColor green "Connection to the eMASS API is sucessful with code" $connectcode
    Write-Host ""

} else {

    Write-Host ""
    Write-Host -ForegroundColor red "Connection to the API failed with code" $connectcode
    Write-Host -ForegroundColor Yellow "Check the API key and Cert thumprint"
    break
}

#check if data Report file exists
if (Test-Path $dataPath) {
    Write-Host ""
    Write-Host -ForegroundColor green "Data File Found at location: "$dataPath
    Write-Host ""
}else {
    Write-Host ""
    Write-Host -ForegroundColor red "Unable to locate data Report at provided file location."
    Write-Host -ForegroundColor Yellow "Verify the data Report file location"
    break
}


#check if Checklist file exists
if (Test-Path $ChecklistPath) {
    Write-Host ""
    Write-Host -ForegroundColor green "Blank Checklist File Found at location: "$ChecklistPath
    Write-Host ""
}else {
    Write-Host ""
    Write-Host -ForegroundColor red "Unable to locate blank checklist at provided file location."
    Write-Host -ForegroundColor Yellow "Verify the file location"
    break
}


#Pull initial system information
$systemdatademo = Get-Content (join-path $DemoAssets "SystemInfo.json" ) | ConvertFrom-Json
$systemdata = $systemdatademo.data | Where-Object {$_.'systemId' -eq $SystemID}

$systemname =           $systemdata | Select-Object -ExpandProperty name
$systemACR =            $systemdata | Select-Object -ExpandProperty acronym
$systemDescription =    $systemdata | Select-Object -ExpandProperty description
$systemVersion =        $systemdata | Select-Object -ExpandProperty versionReleaseNo

Write-Host -ForegroundColor Cyan "System ID:          "$SystemID
Write-Host -ForegroundColor Cyan "System Name:        "$systemname
Write-Host -ForegroundColor Cyan "System Acronym:     "$systemACR
Write-Host -ForegroundColor Cyan "System Version:     "$systemVersion
Write-Host ""
Write-Host -ForegroundColor Cyan "System Description: "$systemDescription
Write-Host ""


#pull system criticality information
$RegistrationType =     $systemdata | Select-Object -ExpandProperty registrationtype
$LifecyclePhase =       $systemdata | Select-Object -ExpandProperty systemLifeCycleAcquisitionPhase
$ATOStatus =            $systemdata | Select-Object -ExpandProperty authorizationStatus
$confidentiality =      $systemdata | Select-Object -ExpandProperty confidentiality
$integrity =            $systemdata | Select-Object -ExpandProperty integrity
$availability =         $systemdata | Select-Object -ExpandProperty availability
$impact =               $systemdata | Select-Object -ExpandProperty impact
$SystemType =           $systemdata | Select-Object -ExpandProperty systemType
$RMFActivity =          $systemdata | Select-Object -ExpandProperty rmfActivity

Write-Host -ForegroundColor Cyan "Registration type is "$RegistrationType
Write-Host -ForegroundColor Cyan "Lifecycle Phase is:  "$LifecyclePhase
Write-Host -ForegroundColor Cyan "Authorization Status:"$ATOStatus
Write-Host ""
Write-Host -ForegroundColor Cyan "Confidentiality is   "$confidentiality
Write-Host -ForegroundColor Cyan "Integrity is         "$integrity
Write-Host -ForegroundColor Cyan "Availability is      "$availability
Write-Host ""
Write-Host -ForegroundColor Cyan "Impact Level is      "$impact
Write-Host ""
Write-Host -ForegroundColor Cyan "System Type is       "$SystemType
Write-Host ""
Write-Host -ForegroundColor Cyan "RMF Phase is         "$RMFActivity
Write-Host ""

#pull classification information and produce human readable format. 
$CUI = $systemdata | Select-Object -ExpandProperty hasCUI
$PII = $systemdata | Select-Object -ExpandProperty hasPII
$PHI = $systemdata | Select-Object -ExpandProperty hasPHI
$NSS = $systemdata | Select-Object -ExpandProperty isNSS
$FMS = $systemdata | Select-Object -ExpandProperty isFinancialManagement

if ($CUI -like "False") {
    Write-Host -ForegroundColor Cyan "CUI: NO"
} Else {
    Write-Host -ForegroundColor Yellow "CUI: YES"
}
if ($PII -like "False") {
    Write-Host -ForegroundColor Cyan "PII: NO"
} Else {
    Write-Host -ForegroundColor yellow "PII: YES"
}

if ($PHI -like "False") {
    Write-Host -ForegroundColor Cyan "PHI: NO"
} Else {
    Write-Host -ForegroundColor Yellow "PHI: YES"
}

if ($NSS -like "False") {
    Write-Host -ForegroundColor Cyan "NSS: NO"
} Else {
    Write-Host -ForegroundColor Yellow "NSS: YES"
}

if ($FMS -like "False") {
    Write-Host -ForegroundColor Cyan "Financial Management: NO"
}else {
    Write-Host -ForegroundColor Yellow "Financial Management: YES"
}

#Pull classification
$classification = $systemdata | Select-Object -ExpandProperty highestSystemDataClassification

Write-Host ""
Write-Host -ForegroundColor Cyan "The highest system classification is: "$classification
Write-Host ""

#Pull Mission criticality display
$MissionCriticality = $systemdata | Select-Object -ExpandProperty missionCriticality

if ($null -eq $MissionCriticality) {
    Write-Host -ForegroundColor Yellow "Mission Criticality: Not Specified (Null)"
} else {
    Write-Host -ForegroundColor Cyan "Mission Criticality: "$MissionCriticality
}

#Pull WorkFlow information 
$WorkFlowData = Get-Content (join-path $DemoAssets "Workflows.json") | ConvertFrom-Json

if ($null -eq $WorkFlowData.data){

    Write-Host ""
    Write-Host -ForegroundColor yellow "System has no active workflows"
    
} else {
    $WorkflowType =     $WorkFlowData.data | Select-Object -ExpandProperty workflow
    $WorkflowName =     $WorkFlowData.data | Select-Object -ExpandProperty name
    $WorkflowStage =    $WorkFlowData.data | Select-Object -ExpandProperty currentStageName

    Write-Host ""
    Write-Host -ForegroundColor Cyan "Workflow Type:  "$WorkflowType
    Write-Host -ForegroundColor Cyan "Workflow Name:  "$WorkflowName
    Write-Host -ForegroundColor Cyan "Workflow Stage: "$WorkflowStage
}


#Pull System Hardware information. 
$HardwareData = Get-Content (join-path $DemoAssets "HardwareDetailsDashboard.json") | ConvertFrom-Json
$HardwareDataSorted = $HardwareData.data | Where-Object {$_.'System ID' -eq $SystemID} 

if ($null -eq $HardwareDataSorted) {
    Write-Host ""
    Write-Host -ForegroundColor Red "eMASS Hardware data not available for system"
    Write-Host ""
} else {
    Write-Host ""
    Write-Host -ForegroundColor Green "Found eMASS Hardware Data for System ID "$SystemID
    Write-Host "" 
}

#pull system software information. 
$SoftwareData = Get-Content (join-path $DemoAssets "SoftwareDetailsDashboard.json") | ConvertFrom-Json
$SoftwareDataSorted = $SoftwareData.data | Where-Object {$_.'System ID' -eq $SystemID} 

if ($null -eq $SoftwareDataSorted) {
    Write-Host ""
    Write-Host -ForegroundColor Red "eMASS Software data not available for system"
    Write-Host ""
} else {
    Write-Host ""
    Write-Host -ForegroundColor Green "Found eMASS Software Data for System ID "$SystemID
    Write-Host "" 
}

#Pull Artifact information for System
$ArtifactsSummary = Get-Content (join-path $DemoAssets "ArtifactSummary.json") | ConvertFrom-Json
$ArtifactsSumSys = $ArtifactsSummary.data | Where-Object {$_.'System ID' -eq $SystemID} 

$ArtifactNumber = $ArtifactsSumSys | Select-Object -ExpandProperty "Total Artifacts"

if ($null -eq $ArtifactNumber) {
    Write-Error "Unable to Pull number of system artifacts"
} else {
    Write-Host -ForegroundColor Green "$ArtifactNumber Artifacts found for system"
    Write-Host "" 
}

#Pull Artifact Details
$ArtifactDetails = Get-Content (join-path $DemoAssets "ArtifactDetails.json") | ConvertFrom-Json 
$ArtifactDetailsDataRaw = $ArtifactDetails.data
$ArtifactDetailsData = $ArtifactDetailsDataRaw | Where-Object {$_."System ID" -eq $SystemID}

if ($null -eq $ArtifactDetailsData) {
    Write-Error "Unable to Pull system artifact details"
} else {
    Write-Host -ForegroundColor Green "Successfully Pulled Artifact Detail Data."
    Write-Host "" 
}


#Pull Comparison Data from data and perform one test comparison. 
$dataReport = Import-Csv -Path $dataPath
$dataID = $systemdata | Select-Object -ExpandProperty dataId

$AITRNumber = $dataReport[0]."DATA Number"

if ($dataID -eq $AITRNumber){
    Write-Host ""
    Write-Host -ForegroundColor green "data Report number and eMASS data ID Match: Data Looks Good"

} else {
    Write-Host ""
    Write-Error "***data number and eMASS data ID do NOT Match: data Report may not be for this system***"
    Write-Host -ForegroundColor Red "The AITR Number in eMASS is: "$dataID
    Write-Host -ForegroundColor Red "The AITR Number in data is: "$AITRNumber
}


#Set Counters to zero
$PassCount = 0
$FailCount = 0
$ConcernCount = 0
$NACount = 0 

#begin performing tests from deep dive spreadsheet.

Write-Host ""
Write-Output "Begining Deep Dive Testing . . . "
Write-Host ""

Start-Sleep -Seconds 5


Write-host -ForegroundColor Cyan "Test 1: Assess Only Approval Path"

if($RegistrationType -like "Assess and Authorize"){
    Write-Host -ForegroundColor Gray "Test is not applicable (Not Assess Only)" -InformationVariable Test1Info
    $Test1Result = "N/A"
    $NACount++
} else {
    Write-Host "System registration type is Assess Only"
    Write-Host "Test is within scope for system"

    if ($SystemType -notlike "IS Major System"){
        if ($MissionCriticality -like "*critical*") {
            Write-Host -ForegroundColor Red "Test Failed: Mission Critical System Cannot be Assess Only" -InformationVariable Test1Info
            $Test1Result = "FAIL"
            $FailCount++

        } elseif ($MissionCriticality -like "*Essential*") {
            if ($confidentiality -like "Low" -and $integrity -like "Low" -and $availability -like "Low"){
                Write-Host -ForegroundColor Green "Test Passed: CIA levels match mission criticality" -InformationVariable Test1Info
                $Test1Result = "PASS"
                $PassCount++
            } else{
                Write-Host -ForegroundColor Red "Test Failed: CIA levels must be low for Mission essential system to be Assess only" -InformationVariable Test1Info
                $Test1Result = "FAIL"
                $FailCount++
            }
        
        } elseif ($MissionCriticality -like "*Support*") {
            if ($confidentiality -like "High") {
                Write-Host -ForegroundColor Red "Test Failed: CIA levels must be medium or low for Mission support system to be Assess only" -InformationVariable Test1Info
                $Test1Result = "FAIL"
                $FailCount++
            } elseif ($integrity -like "High") {
                Write-Host -ForegroundColor Red "Test Failed: CIA levels must be medium or low for Mission support system to be Assess only" -InformationVariable Test1Info
                $Test1Result = "FAIL"
                $FailCount++
            } elseif ($availability -like "High") {
                Write-Host -ForegroundColor Red "Test Failed: CIA levels must be medium or low for Mission support system to be Assess only" -InformationVariable Test1Info
                $Test1Result = "FAIL"
                $FailCount++
            } else {
                Write-Host -ForegroundColor Green "Test Passed: CIA levels match mission criticality" -InformationVariable Test1Info
                $Test1Result = "PASS"
                $PassCount++
            }

        } elseif ($null -eq $MissionCriticality) {
            Write-Host -ForegroundColor Yellow "Unable to complete test: Mission Criticality not defined" -InformationVariable Test1Info
            $test1result = "CONCERN"
            $ConcernCount++
        }

    } else {
        Write-Host -ForegroundColor Red "Test Failed: Major System Cannot be Assess Only" -InformationVariable Test1Info
        $Test1Result = "FAIL"
        $FailCount++
    }
}




Write-Host ""
Write-host -ForegroundColor Cyan "Test 2: Workflow title has the correct Naming Convention"
Write-Host ""

if ($null -eq $WorkFlowData.data){

    Write-Host -ForegroundColor Gray "Test is not applicable: System has no active workflows" -InformationVariable Test2Info
    Write-Host ""
    $Test2Result = "N/A"
    $NACount++

} else {

    #These are the naming conventions provided by the test, more can be added if needed using elseif. 
    if ($WorkflowName -like "'ConMon ' + $systemACR + ' - Initial" -or $WorkflowName -like "'ConMon ' + $systemACR + ' - Ongoing") {

        Write-Host ""
        Write-Host -ForegroundColor green "Test Passed: ConMon has the correct naming convention" -InformationVariable Test2Info
        Write-Host ""
        $Test2Result = "PASS"
        $PassCount++

    } elseif ($WorkflowName -like "'ATC ' + $systemACR + ' - Initial" -or $WorkflowName -like "'ATC ' + $systemACR + ' - Ongoing") {
        Write-Host ""
        Write-Host -ForegroundColor green "Test Passed: ATC has the correct naming convention" -InformationVariable Test2Info
        Write-Host ""
        $Test2Result = "PASS"
        $PassCount++

    } elseif ($WorkflowName -like "'ConMon and ATC ' + $systemACR + ' - Initial" -or $WorkflowName -like "'ConMon and ATC ' + $systemACR + ' - Ongoing") {
        Write-Host ""
        Write-Host -ForegroundColor green "Test Passed: ConMon and ATC has the correct naming convention" -InformationVariable Test2Info
        Write-Host ""
        $Test2Result = "PASS"
        $PassCount++
    } else {
        Write-Host ""
        Write-Host -ForegroundColor red "Test Failed: WorkFlow Naming convention is not correct or could not be verified: "$WorkflowName -InformationVariable Test2Info
        Write-Host ""
        $Test2Result = "FAIL"
        $FailCount++
    }

}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 3: eMASS System Name matches data Item Name"
Write-Host ""

$dataName = $dataReport[0]."Item Name"

if ($null -eq $systemname){ 
    Write-Host -ForegroundColor Red "Test Failed: eMASS system name not defined" -InformationVariable Test3Info
    $Test3Result = "FAIL"
    $FailCount++
} elseif ($systemname -eq $dataName) {
    Write-Host -ForegroundColor Green "Test Passed: eMASS and data system name is: "$systemname -InformationVariable Test3Info
    $Test3Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "Test Failed: eMASS and data names do not match" -InformationVariable Test3Info
    Write-Host -ForegroundColor Red "eMASS Name: "$systemname
    Write-Host -ForegroundColor Red "data Name: "$dataName
    $Test3Result = "FAIL"
    $FailCount++
}
  


Write-Host ""
Write-host -ForegroundColor Cyan "Test 4: eMASS Acronym matches data Acronym"
Write-Host ""

$dataAcronym = $dataReport[0]."Acronym"

if ($null -eq $systemACR){
    Write-Host -ForegroundColor Red "Test Failed: eMASS system acronym is not defined" -InformationVariable Test4Info
    $Test4Result = "FAIL"
    $FailCount++
} elseif ($systemACR -eq $dataAcronym) {
    Write-Host -ForegroundColor Green "Test Passed: eMASS and data system acronym is: "$systemACR -InformationVariable Test4Info
    Write-Host ""
    $Test4Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "Test Failed: eMASS and data Acronym do not match" -InformationVariable Test4Info
    Write-Host -ForegroundColor Red "eMASS Acronym: "$systemACR
    Write-Host -ForegroundColor Red "data Acronym: "$dataAcronym
    $Test4Result = "PASS"
    $PassCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 5: Connection point(s) details provided if applicable."
Write-Host ""

$connectivityCcsd = $systemdata | Select-Object connectivityCcsd
$connectivityCcsdtext = $systemdata | Select-Object -ExpandProperty connectivityCcsd

if ([string]::IsNullOrEmpty($connectivityCcsdtext)) {

    Write-Host -ForegroundColor Yellow "CONCERN: Connection Points are not provided" -InformationVariable Test5Info
    $Test5Result = "CONCERN"
    $ConcernCount++

} else {
    Write-Host -ForegroundColor Green "Test Passed: Connectivity Type is: "$connectivityCcsdtext -InformationVariable Test5Info
    $Test5Result = "PASS"
    $PassCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 6: Version / Release Number matches System"
Write-Host ""

if ($null -eq $systemVersion){
    Write-Host -ForegroundColor Red "Test Failed: System Version not entered" -InformationVariable Test6Info
    $Test6Result = "FAIL"
    $FailCount++
} else {
    Write-Host -ForegroundColor Green "Test Passed: System Version number is: "$systemVersion -InformationVariable Test6Info
    Write-Host -ForegroundColor Yellow "Verify System Version Number is correct"
    $Test6Result = "PASS"
    $PassCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 7: Verify System Type is Correct"
Write-Host ""

if ($null -eq $SystemType){
    Write-Host -ForegroundColor Red "Test Failed: System Type not entered" -InformationVariable Test7Info
    $Test7Result = "FAIL"
    $FailCount++
} else {
    Write-Host -ForegroundColor Green "Test Passed: System Type is: "$SystemType -InformationVariable Test7Info
    Write-Host -ForegroundColor Yellow "Verify System Type is correct"
    $Test7Result = "PASS"
    $PassCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 8: Authorization Termination Date"
Write-Host ""

$AMPSAuthTermDate = $dataReport[0]."NIPR - Authorization Expiration Date"

$authorizationStatus = $systemdata | Select-Object -ExpandProperty authorizationStatus
$authTerminationDate = $systemdata | Select-Object -ExpandProperty authTerminationDate

[datetime]$origin = '1970-01-01'
$TermDate = $origin.AddSeconds($authTerminationDate)
$termdate2 = ($TermDate).ToString("yyyy-MM-dd")

if ($authorizationStatus -like "Not Yet Authorized") {
    
    Write-Host -ForegroundColor Gray "Test is not Applicable: System is not yet authorized" -InformationVariable test8info
    $test8result = "N/A"
    $NACount++

} else {
    
    if($null -eq $authTerminationDate) {

        Write-Host -ForegroundColor Red "Test Failed: System is authorized, but no date is provided" -InformationVariable test8info
        $test8result = "FAIL"
        $FailCount++
    } else {
        
        #eMASS uses epoch time in seconds to keep date, so it has to be converted to readable format. 
        $AuthDate = $authTerminationDate
        [datetime]$origin = '1970-01-01'
        
        $TodayDate = (New-TimeSpan -Start (Get-Date "01/01/1970") -End (Get-Date)).TotalSeconds

        if($authTerminationDate -le $TodayDate){
            Write-Host -ForegroundColor Yellow "CONCERN: Authorization is expired: "$origin.AddSeconds($authTerminationDate) -InformationVariable test8info
            $test8result = "CONCERN"
            $ConcernCount++
        } else {
            if($termdate2 -eq $AMPSAuthTermDate) {
                Write-Host -ForegroundColor Green "Test Passed: The authorization termination date matches data and is: "$origin.AddSeconds($authTerminationDate) -InformationVariable test8info
                $test8result = "PASS"
                $PassCount++
            } else {
                Write-Host -ForegroundColor Red "Test Failed: The authorization Termination Date does not match data." -InformationVariable test8info
                Write-Host -ForegroundColor Red "eMASS Auth Termination Date is: "$TermDate2
                Write-Host -ForegroundColor Red "data Auth Termination Date is: "$AMPSAuthTermDate
                $test8result = "FAIL"
                $FailCount++
            }
        }


    }

}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 9: National Security System"
Write-Host ""

$dataClassification = $dataReport[0]."Classification level of network"
$dataNSS = $dataReport[0]."NIPR - National Security System"

if($null -eq $classification -or $null -eq $NSS){
    Write-Host -ForegroundColor Red "Test Failed: System Highest Classification or NSS Information not provided" -InformationVariable Test9Info
    $Test9Result = "FAIL"
    $FailCount++
} elseif ($NSS -like "False" -and $dataNSS -like "No") {
    Write-Host -ForegroundColor Green "Test Passed: NSS Matches eMASS and data" -InformationVariable Test9Info
    $Test9Result = "PASS"
    $PassCount++
} elseif ($NSS -like "True" -and $dataNSS -like "Yes") {
    Write-Host -ForegroundColor Green "Test Passed: NSS Matches eMASS and data" -InformationVariable Test9Info
    $Test9Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "Test Failed: eMASS NSS and data NSS do not match or were undefined." -InformationVariable Test9Info
    Write-Host -ForegroundColor Red "eMASS NSS is: "$NSS
    Write-Host -ForegroundColor Red "data NSS is: "$dataNSS
    $Test9Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 10: National Security System' checklist filled out completely"
Write-Host ""

#pull system details API endpoint. 
$systemdetails = Get-Content (join-path $DemoAssets "SystemDetailsDashboard.json") | ConvertFrom-Json
$SystemDetailsSorted = $systemdetails.data | Where-Object {$_.'System Id' -eq $SystemID} 

$NSSQuestions = $SystemDetailsSorted | Select-Object -ExpandProperty "NSS Questionnaire Completed"

if ($null -eq $NSSQuestions) {
    Write-Host -ForegroundColor Red "Test Failed: NSS Questionare has not been completed or is undefined." -InformationVariable Test10Info
    $test10result = "FAIL"
    $FailCount++
} elseif ($NSSQuestions -like "Yes") {
    Write-Host -ForegroundColor Green "PASS: NSS Questions have been completed." -InformationVariable Test10Info
    $test10result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "Test Failed: NSS Questionare has not been completed or is undefined." -InformationVariable Test10Info
    $test10result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 11: Financial Management System matches data"
Write-Host ""

$dataFMS = $dataReport[0]."Accounting System or Financial Feeder System"

if($null -eq $FMS){
    Write-Host -ForegroundColor Red "Test Failed: Financial Management information not provided" -InformationVariable Test11Info
    $Test11Result = "FAIL"
    $FailCount++
} elseif ($FMS -like "True" -and $dataFMS -like "*Yes*") {
    Write-Host -ForegroundColor Green "Test Passed: eMASS and data information match" -InformationVariable Test11Info
    $Test11Result = "PASS"
    $PassCount++
} elseif ($FMS -like "False" -and $dataFMS -like "*No*") {
    Write-Host -ForegroundColor Green "Test Passed: eMASS and data information match" -InformationVariable Test11Info
    $Test11Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "Test Failed: eMASS and data do not match." -InformationVariable Test11Info
    Write-Host -ForegroundColor Red "eMASS FMS: "$FMS
    Write-Host -ForegroundColor Red "data FMS: "$dataFMS
    $Test11Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 12: Reciprocity System is Yes"
Write-Host ""

$Reciprocity = $systemdata | Select-Object -ExpandProperty isReciprocity

if ($null -eq $Reciprocity){
    Write-Host -ForegroundColor Red "Test Failed: Reciprocity System is Not provided" -InformationVariable Test12Info
    $Test12Result = "FAIL"
    $FailCount++
} elseif ($Reciprocity -like "True") {
    Write-Host -ForegroundColor Green "Test Passed: Reciprocity System is YES" -InformationVariable Test12Info
    $Test12Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "Test Failed: Reciprocity System is NO" -InformationVariable Test12Info
    $Test12Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 13: Public Facing/Auth boundary"
Write-Host ""

$Public = $systemdata | Select-Object -ExpandProperty isPublicFacing
$WhiteListId = $systemdata | Select-Object -ExpandProperty whitelistId
$WhiteListInventory = $systemdata | Select-Object -ExpandProperty whitelistInventory

if ($null -eq $Public) {
    Write-Host -ForegroundColor Red "Test Failed: Public Facing information is not provided" -InformationVariable Test13Info
    $Test13Result = "FAIL"
    $FailCount++
} elseif ($Public -like "False") {
    Write-Host -ForegroundColor Gray "Test is not applicable: System is not public facing" -InformationVariable Test13Info
    $Test13Result = "N/A"
    $NACount++
} elseif ($Public -like "True") {
    
    if ($null -eq $WhiteListId -or $null -eq $WhiteListInventory) {
        Write-Host -ForegroundColor Red "Test Failed: Whitelist ID or Inventory not provided" -InformationVariable Test13Info
        $Test13Result = "FAIL"
        $FailCount++
    } else {
        Write-Host -ForegroundColor Green "Test Passed: "$WhiteListId $WhiteListInventory -InformationVariable Test13Info
        Write-Host -ForegroundColor Yellow "Verify accuracy of information"
        $Test13Result = "PASS"
        $PassCount++
    }

}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 14: Systems contains CUI, PII and/or PHI and matches data"
Write-Host ""

#translate eMASS True/False into Yes/No
if ($CUI -like "False") {
    $CUI2 = "No"
} Else {
    $CUI2 = "Yes"
}
if ($PII -like "False") {
    $PII2 = "No"
} Else {
    $PII2 = "Yes"
}

if ($PHI -like "False") {
    $PHI2 = "No"
} Else {
    $PHI2 = "Yes"
}

$dataPII = $dataReport[0]."PIA Required"
$dataPHI = $dataReport[0]."Does the system contain Protected Health Information (PHI)"

#Translate data data into yes or no. 
if ($dataPII -like "*Yes*"){
    $dataPII2 = "Yes"
} else {
    $dataPII2 = "No"
}

#run checks. there is no CUI field in data.
if ($PII2 -eq $dataPII2 -and $PHI2 -eq $dataPHI) {
    Write-Host -ForegroundColor Green "Test Passed: PHI and PII values match data. NOTE: data does not have CUI value to complete comparison." -InformationVariable Test14Info
    $Test14Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "Test Failed: PII or PHI values do not match. NOTE: data does not have CUI value to complete comparison." -InformationVariable Test14Info
    Write-Host -ForegroundColor Red "data PII: "$dataPII
    Write-Host -ForegroundColor Red "eMASS PII: "$PII2
    Write-Host -ForegroundColor Red "data PHI: "$dataPHI
    Write-Host -ForegroundColor Red "eMASS PHI: "$PHI2
    $Test14Result = "FAIL"
    $FailCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 15: System Description matches data Description"
Write-Host ""

$dataDescription = $dataReport[0]."Description"

if ($null -eq $systemDescription) {
    Write-Host -ForegroundColor Red "Test Failed: System Description Missing" -InformationVariable Test15Info
    $Test15Result = "FAIL"
    $FailCount++
} elseif ($systemDescription -like $dataDescription) {
    Write-Host -ForegroundColor Green "Test Passed: System description matches data and eMASS: "$systemDescription -InformationVariable Test15Info
    $Test15Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "Test Failed: System Descriptions do not match" -InformationVariable Test15Info
    Write-Host ""
    Write-Host -ForegroundColor Red "eMASS Description: "$systemDescription
    Write-Host ""
    Write-Host -ForegroundColor Red "data Description: "$dataDescription
    $Test15Result = "FAIL"
    $FailCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 16: data ID matches data AITR Number"
Write-Host ""

if ($AITRNumber -eq $dataID){
    Write-Host -ForegroundColor Green "Test Passed: AITR Numbers match: "$dataID -InformationVariable Test16Info
    $Test16Result = "PASS"
    $PassCount++
}else {
    Write-Host -ForegroundColor Red "Test Failed: AITR Numbers do not match" -InformationVariable Test16Info
    Write-Host -ForegroundColor Red "eMASS data ID: " $dataID
    Write-Host -ForegroundColor Red "data AITR Number: "$AITRNumber
    $Test16Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 17: System User Categories' Identify roles, responsibilities and categories for system"
Write-Host ""

Write-Host -ForegroundColor Yellow "eMASS API does not have data for this test." -InformationVariable Test17Info
$Test17Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-host -ForegroundColor Cyan "Test 18: Is this a Cloud Computer?"
Write-Host ""

#get cloud information from eMASS
$Cloud = $systemdata | Select-Object -ExpandProperty cloudComputing
$CloudType = $systemdata | Select-Object -ExpandProperty cloudType
$SAAS = $systemdata | Select-Object -ExpandProperty isSaaS
$PAAS = $systemdata | Select-Object -ExpandProperty isPaaS
$IAAS = $systemdata | Select-Object -ExpandProperty isIaaS
$OAAS = $systemdata | Select-Object -ExpandProperty otherServiceModels

#get cloud information from data
$dataSaaS = $dataReport[0]."Is this a SaaS System"
$dataCloud = $dataReport[0]."Cloud Assessment Designation"
$dataCloudType = $dataReport[0]."Cloud Service Type"

#translate data into useable format. 
if ($dataCloud -like "System is hosted in the cloud"){
    $dataCloud2 = "True"
} elseif ($dataCloud -like "Cloud computing is NOT applicable for this system") {
    $dataCloud2 = "False"
} elseif ($dataCloud -like "-") {
    $dataCloud2 = $null
} elseif ($dataCloud -like "Cloud computing had been considered, but was not selected") {
    $dataCloud2 = "False"
} elseif ($dataCloud -like "Cloud computing has NOT been considered") {
    $dataCloud2 = "False"
} elseif ($dataCloud -like "This investment is considering cloud computing") {
    $dataCloud2 = "False"
} elseif ($dataCloud -like "This system is migrating to the cloud") {
    $dataCloud2 = "True"
}

if ($dataSaaS -like "Yes") {
    $dataSaaS2 = "True"
} elseif ($dataSaaS -like "No") {
    $dataSaaS2 = "False"
} elseif ($dataSaaS -like "-") {
    $dataSaaS2 = $null
} elseif ($null -eq $dataSaaS) {
    $dataSaaS2 = $null
}

if ($dataCloudType -like "*SaaS*") {
    $dataSaaS3 = "True"
} else {
    $dataSaaS3 = "False"
}

if ($dataCloudType -like "*PaaS*") {
    $dataPaaS3 = "True"
} else {
    $dataPaaS3 = "False"
}

if ($dataCloudType -like "*IaaS*") {
    $dataIaaS3 = "True"
} else {
    $dataIaaS3 = "False"
}

#run the checks
if ($Cloud -like "True"){
    if ($null -eq $CloudType -or $null -eq $SAAS -or $null -eq $PAAS -or $null -eq $IAAS) {
        Write-Host -ForegroundColor Red "Test Failed: Cloud System is Yes, But cloud type or service models are missing." -InformationVariable Test18Info
        Write-Host -ForegroundColor Red "Cloud: "$Cloud
        Write-Host -ForegroundColor Red "Cloudtype: "$CloudType
        Write-Host -ForegroundColor Red "SaaS: "$SAAS
        Write-Host -ForegroundColor Red "PaaS: "$PAAS
        Write-Host -ForegroundColor Red "IaaS: "$IAAS
        $Test18Result = "FAIL"
        $FailCount++
    } else {
        if ($SAAS -eq $dataSaaS2 -and $Cloud -eq $dataCloud2 ) {
            if ($SAAS -like $dataSaaS3 -and $PAAS -like $dataPaaS3 -and $IAAS -like $dataIaaS3) {
                Write-Host -ForegroundColor Green "Cloud data in eMASS matches data" -InformationVariable Test18Info
                $Test18Result = "PASS"
                $PassCount++
            } else {
                Write-Host -ForegroundColor Red "Test Failed: Cloud is Yes, but service models do not match data" -InformationVariable Test18Info
                Write-Host -ForegroundColor Red "eMASS SAAS: "$SAAS
                Write-Host -ForegroundColor Red "eMASS PAAS: "$PAAS
                Write-Host -ForegroundColor Red "eMASS IAAS: "$IAAS
                Write-Host -ForegroundColor Red "data SAAS: "$dataSaaS3
                Write-Host -ForegroundColor Red "data PAAS: "$dataPaaS3
                Write-Host -ForegroundColor Red "data IAAS: "$dataIaaS3
                $Test18Result = "FAIL"
                $FailCount++
            }
        } else {
            Write-Host -ForegroundColor Red "Test Failed: data Cloud value or software as a service do not match eMASS." -InformationVariable Test18Info
            Write-Host -ForegroundColor Red "eMASS SaaS: "$SAAS
            Write-Host -ForegroundColor Red "data SaaS: "$dataSaaS2
            Write-Host -ForegroundColor Red "eMASS Cloud: "$Cloud
            Write-Host -ForegroundColor Red "data Cloud: "$dataCloud2
            $Test18Result = "FAIL"
            $FailCount++
        }
    } 
} elseif ($Cloud -like "False") {
    if ($Cloud -like $dataCloud2) {
        Write-Host -ForegroundColor Green "Test Passed: Cloud data in eMASS matches data" -InformationVariable Test18Info
        $Test18Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "Test Failed: data Cloud value does not match eMASS." -InformationVariable Test18Info
        Write-Host -ForegroundColor Red "eMASS Cloud: "$Cloud
        Write-Host -ForegroundColor Red "data Cloud: "$dataCloud2
        $Test18Result = "FAIL"
        $FailCount++
    }
} elseif ($null -eq $Cloud) {
    Write-Host -ForegroundColor Red "Test Failed: Cloud information question not answered in eMASS" -InformationVariable Test18Info
    $Test18Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 19: Does the commercial cloud system have a confidentiality and integrity of HIGH?"
Write-Host ""

if ($Cloud -like "True") {
    if ($confidentiality -like "High" -and $integrity -like "High"){
        Write-Host -ForegroundColor Green "Test Passed: Cloud system has confidentiality and integrity of High" -InformationVariable Test19Info
        $Test19Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Green "Test Failed: Cloud system does not have confidentiality and integrity of High" -InformationVariable Test19Info
        $Test19Result = "FAIL"
        $FailCount++
    }
} else {
    Write-Host -ForegroundColor Gray "Test is not applicable: System is not Cloud" -InformationVariable Test19Info
    $Test19Result = "N/A"
    $NACount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 20: Does the Cloud Service Offering (CSO) have a current DoD PA?"
Write-Host ""

if ($cloud -like "True") {
    Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have data for this test." -InformationVariable Test20Info
    $Test20Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Gray "Test is not applicable: System is not Cloud" -InformationVariable Test20Info
    $Test20Result = "N/A"
    $NACount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 21: PPSM Registry Number Provided?"
Write-Host ""

$PPSMNumber = $systemdata | Select-Object -ExpandProperty ppsmRegistryNumber

if ($SAAS -like "True"){
    if ($null -eq $PPSMNumber) {
        Write-Host -ForegroundColor Red "Test Failed: System is SaaS, but no PPSM Regustration number provided." -InformationVariable Test21Info
        $Test21Result = "FAIL"
        $FailCount++
    } else {
        Write-Host -ForegroundColor Green "Test Passed: System is SaaS, and PPSM Registration number is: "$PPSMNumber -InformationVariable Test21Info
        $Test21Result = "PASS"
        $PassCount++
    }
} else {
    Write-Host -ForegroundColor Gray "Test is not applicable: System is not SaaS" -InformationVariable Test21Info
    $Test21Result = "N/A"
    $NACount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 22: System Authorization Boundary is current & accurate, has an Executive Summary on the System Details tab, the Artifact is Linked or attached?"
Write-Host ""

#pull specific artifact data for test. 
$SystemAuthBoundary = $ArtifactDetailsData | Where-Object {$_."Artifact Name" -eq "Authorization Boundary Diagram"} 
$SystemAuthBoundaryFile = $SystemAuthBoundary | Select-Object -ExpandProperty Filename
$SystemAuthBoundaryDate = $SystemAuthBoundary | Select-Object -ExpandProperty "Signed Date"

#only take one date value in the event of a duplicate.
$SystemAuthBoundaryDate = $SystemAuthBoundaryDate | Select-Object -First 1

#calculate dates needed for documents being older than one year. 
$OneYearAgoDate = (Get-Date).AddDays(-365)
$OneYearAgoEpoch = (New-TimeSpan -Start (Get-Date "01/01/1970") -End ($OneYearAgoDate)).TotalSeconds

#make date human readable
[datetime]$origin = '1970-01-01'
$SystemAuthBoundaryDate2 = $origin.AddSeconds($SystemAuthBoundaryDate)


if ($null -eq $SystemAuthBoundary) {
    Write-Host -ForegroundColor Red "Test Failed: System Authorization Boundary Artifact was not Found" -InformationVariable Test22Info
    $Test22Result = "FAIL"
    $FailCount++
} else {
    if ($SystemAuthBoundaryDate -le $OneYearAgoEpoch){
        Write-Host -ForegroundColor Red "Test Failed: System Authorization Boundary Artifact is older than one year:"$SystemAuthBoundaryDate2 -InformationVariable Test22Info
        $Test22Result = "FAIL"
        $FailCount++
    } else {
        Write-Host -ForegroundColor Green "Test Passed: System Authorization Boundary artifact is current and file name is: "$SystemAuthBoundaryFile -InformationVariable Test22Info
        Write-Host -ForegroundColor Yellow "Verify Accuracy of Artifact Information"
        $Test22Result = "PASS"
        $PassCount++
    }
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 23: Are the HW & SW Baselines populated?"
Write-Host ""

$hardwareSoftwareFirmware = $ArtifactDetailsData | Where-Object {$_."Artifact Name" -eq "Hardware Software Firmware Diagram"}
$hardwareSoftwareFirmwareFile = $hardwareSoftwareFirmware | Select-Object -ExpandProperty Filename
$hardwareSoftwareFirmwareDate = $hardwareSoftwareFirmware | Select-Object -ExpandProperty "Last Reviewed"

#only take one date value in the event of a duplicate.
$hardwareSoftwareFirmwareDate2 = $hardwareSoftwareFirmwareDate | Select-Object -First 1

#make date human readable
[datetime]$origin = '1970-01-01'
$hardwareSoftwareFirmwareDate3 = $origin.AddSeconds($hardwareSoftwareFirmwareDate2)

if ($null -eq $hardwareSoftwareFirmware) {
    Write-Host -ForegroundColor Red "Test Failed: Hardware / Software / Firmware Artifact was not Found" -InformationVariable Test23Info
    $Test23Result = "FAIL"
    $FailCount++
}elseif ($null -eq $HardwareDataSorted -or $null -eq $SoftwareDataSorted) {
    Write-Host -ForegroundColor Red "Test Failed: Hardware or Software baseline was not Found" -InformationVariable Test23Info
    $Test23Result = "FAIL"
    $FailCount++
} elseif ($hardwareSoftwareFirmwareDate2 -le $OneYearAgoEpoch) {
    Write-Host -ForegroundColor Red "Test Failed: Hardware / Software / Firmware Artifact review is greater than one year old: "$hardwareSoftwareFirmwareDate3 -InformationVariable Test23Info
    $Test23Result = "FAIL"
    $FailCount++
} else {
    Write-Host -ForegroundColor Green "Test Passed: Hardware / Software / Firmware Artifact is current and file name is: "$hardwareSoftwareFirmwareFile -InformationVariable Test23Info
    Write-Host -ForegroundColor Yellow "Verify Accuracy of Artifact Information"
    $Test23Result = "PASS"
    $PassCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 24: System Enterprise and Information Security Architecture?"
Write-Host ""

$InfoSecArch = $ArtifactDetailsData | Where-Object {$_."Artifact Name" -eq "Enterprise and Information Security Architecture Diagram"}
$InfoSecArchfile = $InfoSecArch | Select-Object -ExpandProperty Filename
$InfoSecArchDate = $InfoSecArch | Select-Object -ExpandProperty "Last Modified"

#only take one date value in the event of a duplicate.
$InfoSecArchDate = $InfoSecArchDate | Select-Object -First 1


#make date human readable
[datetime]$origin = '1970-01-01'
$InfoSecArchDate2 = $origin.AddSeconds($InfoSecArchDate)

if ($null -eq $InfoSecArch) {
    Write-Host -ForegroundColor Red "Test Failed: System Enterprise and Information Security Architecture Artifact was not Found" -InformationVariable Test24Info
    $Test24Result = "FAIL"
    $FailCount++
} else {
    if ($InfoSecArchDate -le $OneYearAgoEpoch){
        Write-Host -ForegroundColor Red "Test Failed: System Enterprise and Information Security Architecture Artifact review date is older than one year: "$InfoSecArchDate2 -InformationVariable Test24Info
        $Test24Result = "FAIL"
        $FailCount++
    } else {
        Write-Host -ForegroundColor Green "Test Passed: System Enterprise and Information Security Architecture Artifact is current and file name is: "$InfoSecArchfile -InformationVariable Test24Info
        Write-Host -ForegroundColor Yellow "Verify Accuracy of Artifact Information"
        $Test24Result = "PASS"
        $PassCount++
    }
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 25: Information Flows / Paths?"
Write-Host ""

$InfoFlowPath = $ArtifactDetailsData | Where-Object {$_."Artifact Name" -eq "Information Flows Paths Diagram"}
$InfoFlowPathfile = $InfoFlowPath | Select-Object -ExpandProperty Filename
$InfoFlowPathDate = $InfoSecArch | Select-Object -ExpandProperty "Last Modified"

#only take one date value in the event of a duplicate.
$InfoFlowPathDate = $InfoFlowPathDate | Select-Object -First 1

#make date human readable
[datetime]$origin = '1970-01-01'
$InfoFlowPathDate2 = $origin.AddSeconds($InfoFlowPathDate)


if ($null -eq $InfoFlowPath) {
    Write-Host -ForegroundColor Red "Test Failed: Information Flows / Paths Architecture Artifact was not Found" -InformationVariable Test25Info
    $Test25Result = "FAIL"
    $FailCount++
} else {
    if ($InfoFlowPathDate -le $OneYearAgoEpoch){
        Write-Host -ForegroundColor Red "Test Failed: Information Flows / Paths Architecture Artifact is older than one year: "$InfoFlowPathDate2 -InformationVariable Test25Info
        $Test25Result = "FAIL"
        $FailCount++
    } else {
        Write-Host -ForegroundColor Green "Test Passed: Information Flows / Paths Architecture Artifact is current and file name is: "$InfoFlowPathfile -InformationVariable Test25Info
        Write-Host -ForegroundColor Yellow "Verify Accuracy of Artifact Information"
        $Test25Result = "PASS"
        $PassCount++
    }
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 26: Cloud Service Provider (CSP)?"
Write-Host ""

$NetworkTopology = $ArtifactDetailsData | Where-Object {$_."Artifact Name" -eq "Network Topology Diagram"}

if ($null -eq $NetworkTopology) {
    Write-Host -ForegroundColor Red "Test Failed: Network Topology Diagram could not be found." -InformationVariable Test26Info
    $Test26Result = "FAIL"
    $FailCount++
} elseif ($Cloud -like "False") {
    Write-Host -ForegroundColor Gray "Test is not Applicable: System is not Cloud." -InformationVariable Test26Info
    $Test26Result = "N/A"
    $NACount++
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: Network Tolology Diagram exists but further verification is needed." -InformationVariable Test26Info
    $Test26Result = "CONCERN"
    $ConcernCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 27: Does the Network Topology Diagrams show connection of the CSP to customers via Cloud Access Point (CAP) for sensitive data?"
Write-Host ""

if ($null -eq $NetworkTopology) {
    Write-Host -ForegroundColor Red "Test Failed: Network Topology Diagram could not be found." -InformationVariable Test27Info
    $Test27Result = "FAIL"
    $FailCount++
} elseif ($Cloud -like "False") {
    Write-Host -ForegroundColor Gray "Test is not Applicable: System is not Cloud." -InformationVariable Test27Info
    $Test27Result = "N/A"
    $NACount++
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: Network Tolology Diagram exists but further verification is needed." -InformationVariable Test27Info
    $Test27Result = "CONCERN"
    $ConcernCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 28: Does the Network Topology Diagrams align with the cloud service model?"
Write-Host ""

if ($null -eq $NetworkTopology) {
    Write-Host -ForegroundColor Red "Test Failed: Network Topology Diagram could not be found." -InformationVariable Test28Info
    $Test28Result = "FAIL"
    $FailCount++
} elseif ($Cloud -like "False") {
    Write-Host -ForegroundColor Gray "Test is not Applicable: System is not Cloud." -InformationVariable Test28Info
    $Test28Result = "N/A"
    $NACount++
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: Network Tolology Diagram exists but further verification is needed." -InformationVariable Test28Info
    $Test28Result = "CONCERN"
    $ConcernCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 29: Is there an entry in the DMZ whitelist??"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have data for this test." -InformationVariable Test29Info
$Test29Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-host -ForegroundColor Cyan "Test 30: Network Connection Rules provided? If yes, artifact such as ISA provided?"
Write-Host ""

$ISA = $ArtifactDetailsData | Where-Object {$_."Artifact Name" -eq "Interconnection Security Agreement"} | Sort-Object -Property "Last Reviewed" -Descending | Select-Object -First 1 
$ISAFileName = $ISA | Select-Object -ExpandProperty filename

if ($null -eq $ISA) {
    Write-Host -ForegroundColor Red "Test Failed: No Interconnection Service Agreement has been found." -InformationVariable Test30Info
    $Test30Result = "FAIL"
    $FailCount++
} else {
    Write-Host -ForegroundColor Green "PASS: The ISA has been found but further verification is needed." -InformationVariable Test30Info
    Write-Host -ForegroundColor Green "ISA Artifact File name: "$ISAFileName
    $Test30Result = "PASS"
    $PassCount++
}

Write-Host ""
Write-host -ForegroundColor Cyan "Test 31: Interconnected Information Systems and Identifiers provided? If yes, artifact such as ISA provided?"
Write-Host ""

$IISI = $systemdata | Select-Object -ExpandProperty interconnectedInformationSystemsAndIdentifiers

if ($null -eq $IISI) {
    Write-Host -ForegroundColor Yellow "CONCERN: The Interconnected Information Systems and Identifiers has not been provided, verify this is accurate." -InformationVariable Test31Info
    $Test31Result = "CONCERN"
    $ConcernCount++
} else {
    if ($null -eq $ISA) {
        Write-Host -ForegroundColor Red "Test Failed: The Interconnected Information Systems and Identifiers have been provided, but no ISA Artifact was found." -InformationVariable Test31Info
        $Test31Result = "FAIL"
        $FailCount++
    } else {
        Write-Host -ForegroundColor Green "Test Passed: The Interconnected Information Systems and Identifiers have been provided and the ISA Artifact has been found." -InformationVariable Test31Info
        $Test31Result = "PASS"
        $PassCount++
    }
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 32: Encryption Techniques' provided to protect DAR and DIT [CUI/PII/PH data]?"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have data available for this test" -InformationVariable Test32Info
$Test32Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-host -ForegroundColor Cyan "Test 33: Cryptographic Key Management Information?"
Write-Host ""

if ($CUI -like "True" -or $PII -like "True" -or $PHI -like "True") {
    Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have data available for this test" -InformationVariable Test33Info
    $Test33Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Gray "Not Applicable: System is not CUI/PII/PHI" -InformationVariable Test33Info
    $Test33Result = "N/A"
    $NACount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 34: Assessed 'Non Compliant' and 'Not Applicable' controls without an active POA&M Item = 0 and verify that all failed checks have a POA&M"
Write-Host ""

$noncompliantControls = @()

$ControlsData = Get-Content (join-path $DemoAssets "Controls.json") | ConvertFrom-Json

$POAMData = Get-Content (join-path $DemoAssets "POAMs.json") | ConvertFrom-Json

$ControlsData2 = $ControlsData.data
$POAMData2 = $POAMData.data

$noncompliantControls = $null

foreach ($control in $ControlsData2) {
    if (($control.complianceStatus -eq "NC") -or ($control.complianceStatus -eq "[REDACTED]")) {
        $hasPOAM = $POAMData2 | Where-Object { $_.controlAcronym -like $control.acronym }
        if ($null -eq $hasPOAM) {
            $noncompliantControls += $control | Select-Object -ExpandProperty acronym
        }
    }
}   

if ($null -eq $noncompliantControls) {
    Write-Host -ForegroundColor Green "Test Passed: No Non-Compliant or Not Applicable Controls without POAMS were found." -InformationVariable Test34Info
    $Test34Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "Test Failed: Non-Compliant or Not Applicable Controls were found without POAMs: " $noncompliantControls -InformationVariable Test34Info
    $Test34Result = "FAIL"
    $FailCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 35: Does system have a registration in the Authorizing Official Repository (AO-R)?"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: This test is external to eMASS and cannot be tested automatically." -InformationVariable Test35Info
$Test35Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-host -ForegroundColor Cyan "Test 36: System Location' is correct?"
Write-Host ""

$MainLocation = $SystemDetailsSorted | Select-Object -ExpandProperty "Baseline Location"

if ($null -eq $MainLocation) {
    Write-Host -ForegroundColor Red "FAIL: Location Information is not provided or undefined." -InformationVariable Test36Info
    $Test36Result = "FAIL"
    $FailCount++
} else {
    Write-Host -ForegroundColor Green "PASS: Location is: "$MainLocation -InformationVariable Test36Info
    Write-Host -ForegroundColor Yellow "Verify this information is accurate"
    $Test36Result = "PASS"
    $PassCount ++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 37: Deployment Locations Provided?"
Write-Host ""

$DeployLocation = $SystemDetailsSorted | Select-Object -ExpandProperty "Deployment Locations"

if ($null -eq $DeployLocation) {
    Write-Host -ForegroundColor Red "FAIL: Location Information is not provided or undefined." -InformationVariable Test37Info
    $Test37Result = "FAIL"
    $FailCount++
} else {
    Write-Host -ForegroundColor Green "PASS: Location is: "$DeployLocation -InformationVariable Test37Info
    Write-Host -ForegroundColor Yellow "Verify this information is accurate"
    $Test37Result = "PASS"
    $PassCount ++
}




Write-Host ""
Write-host -ForegroundColor Cyan "Test 38: Baseline Location Provided?"
Write-Host ""

if ($null -eq $MainLocation) {
    Write-Host -ForegroundColor Red "FAIL: Location Information is not provided or undefined." -InformationVariable Test38Info
    $Test38Result = "FAIL"
    $FailCount++
} else {
    Write-Host -ForegroundColor Green "PASS: Location is: "$MainLocation -InformationVariable Test38Info
    Write-Host -ForegroundColor Yellow "Verify this information is accurate"
    $Test38Result = "PASS"
    $PassCount ++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 39: Physical Location(s)' Provided?"
Write-Host ""

$InstallationName = $SystemDetailsSorted | Select-Object -ExpandProperty "Installation Name (Primary Location)"
$StreetAddress = $SystemDetailsSorted | Select-Object -ExpandProperty "Street Address (Primary Location)"
$InstallCity = $SystemDetailsSorted | Select-Object -ExpandProperty "City (Primary Location)"
$InstallState = $SystemDetailsSorted | Select-Object -ExpandProperty "State (Primary Location)"
$InstallZip = $SystemDetailsSorted | Select-Object -ExpandProperty "Zip Code (Primary Location)"

if ($null -eq $InstallationName -or
    $null -eq $StreetAddress -or
    $null -eq $InstallCity -or
    $null -eq $InstallState -or
    $null -eq $InstallZip) {

        Write-Host -ForegroundColor Red "FAIL: Location information missing on undefined" -InformationVariable Test39Info
        Write-Host -ForegroundColor Red "Installation Name: $InstallationName"
        Write-Host -ForegroundColor Red "Street Address: $StreetAddress"
        Write-Host -ForegroundColor Red "City: $installCity"
        Write-Host -ForegroundColor Red "State: $InstallState"
        Write-Host -ForegroundColor Red "Zip: $InstallZip"
        $Test39Result = "FAIL"
        $FailCount++

} else {
    Write-Host -ForegroundColor Green "PASS: Location information provided" -InformationVariable Test39Info
    Write-Host -ForegroundColor Green "Installation Name: $InstallationName"
    Write-Host -ForegroundColor Green "Street Address: $StreetAddress"
    Write-Host -ForegroundColor Green "City: $installCity"
    Write-Host -ForegroundColor Green "State: $InstallState"
    Write-Host -ForegroundColor Green "Zip: $InstallZip"
    $Test39Result = "PASS"
    $PassCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 40: Approved SP obtained within one year of date workflow submitted has to be approved via an A&A or ASR workflow not an Extension workflow?"
Write-Host ""

#get workflow history data and keep only data for correct system and most recent security plan approval. 
$WorkflowHistoryData = Get-Content (join-path $DemoAssets "WorkflowDashboard.json") | ConvertFrom-Json
$WorkflowHistoryDataSorted = $WorkflowHistoryData.data | Where-Object {$_.'systemId' -eq $SystemID} 
$SecurityPlanApprovalWorkflow = $WorkflowHistoryDataSorted | Where-Object {$_.'workflow' -like "Security Plan Approval"} | Sort-Object -Property "lastEditedDate" -Descending | Select-Object -First 1
$SecurityPlanApprovalWorkflowDate = $SecurityPlanApprovalWorkflow | Select-Object -ExpandProperty "lastEditedDate"


#get security plan approval information
$SecurityPlanApproval = $systemdata | Select-Object -ExpandProperty securityPlanApprovalStatus
$SecurityPlanApprovalDate = $systemdata | Select-Object -ExpandProperty securityPlanApprovalDate

#search for security plan artifact
$SecurityPlanArtifact = $ArtifactDetailsData | Where-Object {$_."Artifact Name" -like "*Security Plan*"} | Sort-Object -Property "Last Reviewed" -Descending | Select-Object -First 1 
$SecurityPlanArtifactName = $SecurityPlanArtifact | Select-Object -ExpandProperty "filename"

#calculate difference in dates
$datedifference = $SecurityPlanApprovalDate - $SecurityPlanApprovalWorkflowDate

#make dates human readable
$SecurityPlanApprovalWorkflowDateFull = $origin.AddSeconds($SecurityPlanApprovalWorkflowDate)
$SecurityPlanApprovalDateFull = $origin.AddSeconds($SecurityPlanApprovalDate)


if ($SecurityPlanApproval -like "Approved") {
    if ($null -eq $SecurityPlanApprovalWorkflowDate){
        Write-Host -ForegroundColor Red "FAIL: Security Plan Approval Workflow is not found." -InformationVariable Test40Info
        $Test40Result = "FAIL"
        $FailCount++

    } elseif ($datedifference -gt "31536000") {
        Write-Host -ForegroundColor Red "FAIL: Security Plan approval is greater than one year from security plan workflow." -InformationVariable Test40Info
        Write-Host -ForegroundColor Red "Security Plan Approval Date is: "$SecurityPlanApprovalDateFull
        Write-Host -ForegroundColor Red "Security Plan Workflow Decision Date is: "$SecurityPlanApprovalWorkflowDateFull
        $Test40Result = "FAIL"
        $FailCount++

    } elseif ($datedifference -le "0") {
        Write-Host -ForegroundColor Yellow "CONCERN: Security Plan approval has come before the security plan workflow." -InformationVariable Test40Info
        Write-Host -ForegroundColor Red "Security Plan Approval Date is: "$SecurityPlanApprovalDateFull
        Write-Host -ForegroundColor Red "Security Plan Workflow Decision Date is: "$SecurityPlanApprovalWorkflowDateFull
        $Test40Result = "CONCERN"
        $ConcernCount++

    } else {
        if ($null -eq $SecurityPlanArtifact) {
            Write-Host -ForegroundColor Red "FAIL: Security Plan Artifact was not found." -InformationVariable Test40Info
            $Test40Result = "FAIL"
            $FailCount++
        } else {
            Write-Host -ForegroundColor Green "PASS: Security Plan Approved, SP Workflow Used, SP Artifact Found." -InformationVariable Test40Info
            Write-Host -ForegroundColor Green "Security Plan Approval Date is: "$SecurityPlanApprovalDateFull
            Write-Host -ForegroundColor Green "Security Plan Workflow Decision Date is: "$SecurityPlanApprovalWorkflowDateFull
            Write-Host -ForegroundColor Green "Security Plan Artifact File Name: "$SecurityPlanArtifactName
            $Test40Result = "FAIL"
            $FailCount++
        }
    }
} else {
    Write-Host -ForegroundColor Yellow "FAIL: Security Plan is not Approved. Check Workflow and Artifacts." -InformationVariable Test40Info
    $Test40Result = "FAIL"
    $FailCount++

}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 41: System Life Cycle / Acquisition Phase Provided"
Write-Host ""

$dataLifeCycle = $dataReport[0]."Life Cycle Phase Name"

if ($null -eq $LifecyclePhase) {
    Write-Host -ForegroundColor Yellow "Fail: LifeCycle Phase is not provided." -InformationVariable Test41Info
    $Test41Result = "FAIL"
    $FailCount++
} elseif ($LifecyclePhase -like "*Pre-Milestone A*") {
    if ($dataLifeCycle -like "*Material Solution Analysis*") {
        Write-Host -ForegroundColor Green "PASS: LifeCycle Information provided and matches ATO Status and data." -InformationVariable Test41Info
        $Test41Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "Fail: LifeCycle information does not match data." -InformationVariable Test41Info
        Write-Host -ForegroundColor Red "eMASS Lifecycle: "$LifecyclePhase
        Write-Host -ForegroundColor Red "data Lifecycle:  "$dataLifeCycle
        $Test41Result = "FAIL"
        $FailCount++
    }
} elseif ($LifecyclePhase -like "*Post-Milestone A*") {
    if ($dataLifeCycle -like "*Acquisition, Testing, & Deployment*") {
        Write-Host -ForegroundColor Green "PASS: LifeCycle Information provided and matches ATO Status and data." -InformationVariable Test41Info
        $Test41Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "Fail: LifeCycle information does not match data." -InformationVariable Test41Info
        Write-Host -ForegroundColor Red "eMASS Lifecycle: "$LifecyclePhase
        Write-Host -ForegroundColor Red "data Lifecycle:  "$dataLifeCycle
        $Test41Result = "FAIL"
        $FailCount++
    }
} elseif ($LifecyclePhase -like "*Post-Milestone B*") {
    if ($dataLifeCycle -like "*Engineering & Manufacturing Development*") {
        Write-Host -ForegroundColor Green "PASS: LifeCycle Information provided and matches ATO Status and data." -InformationVariable Test41Info
        $Test41Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "Fail: LifeCycle information does not match data." -InformationVariable Test41Info
        Write-Host -ForegroundColor Red "eMASS Lifecycle: "$LifecyclePhase
        Write-Host -ForegroundColor Red "data Lifecycle:  "$dataLifeCycle
        $Test41Result = "FAIL"
        $FailCount++
    }
} elseif ($LifecyclePhase -like "*Post-Milestone C*") {
    if ($ATOStatus -like "*Authorization to Operate (ATO)*" -or $ATOStatus -like "*Authorization to Operate w/Conditions*" -or $ATOStatus -like "*Interim Authorization to Test*") {
        if ($dataLifeCycle -like "*Production & Deployment*") {
            Write-Host -ForegroundColor Green "PASS: LifeCycle Information provided and matches ATO Status and data." -InformationVariable Test41Info
            $Test41Result = "PASS"
            $PassCount++
        } else {
            Write-Host -ForegroundColor Red "Fail: LifeCycle information does not match data." -InformationVariable Test41Info
            Write-Host -ForegroundColor Red "eMASS Lifecycle: "$LifecyclePhase
            Write-Host -ForegroundColor Red "data Lifecycle:  "$dataLifeCycle
            $Test41Result = "FAIL"
            $FailCount++
        }
    } else {
        Write-Host -ForegroundColor Red "Fail: Systems in Post Milestone C must have a valid ATO, ATOC, or IATT." -InformationVariable Test41Info
        Write-Host -ForegroundColor Red "eMASS Lifecycle: "$LifecyclePhase
        Write-Host -ForegroundColor Red "eMASS ATO Status:"$ATOStatus
        $Test41Result = "FAIL"
        $FailCount++
    }
} elseif ($LifecyclePhase -like "*Post-Full Rate Production/Deployment Decision*") {
    if ($ATOStatus -like "*Authorization to Operate (ATO)*" -or $ATOStatus -like "*Authorization to Operate w/Conditions*" -or $ATOStatus -like "*Interim Authorization to Test*") {
        if ($dataLifeCycle -like "*Operations & Support*") {
            Write-Host -ForegroundColor Green "PASS: LifeCycle Information provided and matches ATO Status and data." -InformationVariable Test41Info
            $Test41Result = "PASS"
            $PassCount++
        } else {
            Write-Host -ForegroundColor Red "Fail: LifeCycle information does not match data." -InformationVariable Test41Info
            Write-Host -ForegroundColor Red "eMASS Lifecycle: "$LifecyclePhase
            Write-Host -ForegroundColor Red "data Lifecycle:  "$dataLifeCycle
            $Test41Result = "FAIL"
            $FailCount++
        }
    } else {
        Write-Host -ForegroundColor Red "Fail: Systems in Full Production must have a valid ATO, ATOC, or IATT." -InformationVariable Test41Info
        Write-Host -ForegroundColor Red "eMASS Lifecycle: "$LifecyclePhase
        Write-Host -ForegroundColor Red "eMASS ATO Status:"$ATOStatus
        $Test41Result = "FAIL"
        $FailCount++
    }
} else {
    Write-Host -ForegroundColor Red "Fail: eMASS Lifecycle information is not in an expected state." -InformationVariable Test41Info
    Write-Host -ForegroundColor Red "eMASS Lifecycle: "$LifecyclePhase
    $Test41Result = "FAIL"
    $FailCount++
}


<#
Test 42: 'Type Authorization' is Yes
#>

Write-Host ""
Write-host -ForegroundColor Cyan "Test 42: Type Authorization is Yes"
Write-Host ""

$TypeAuthorization = $systemdata | Select-Object -ExpandProperty isTypeAuthorization

if ($null -eq $TypeAuthorization) {
    Write-Host -ForegroundColor Red "Fail: Type Authorization is not provided." -InformationVariable Test42Info
    $Test42Result = "FAIL"
    $FailCount++
} elseif ($TypeAuthorization -like "True") {
    Write-Host -ForegroundColor Green "PASS: Type Authorization is Yes." -InformationVariable Test42Info
    $Test42Result = "PASS"
    $PassCount++
} elseif ($TypeAuthorization -like "False") {
    Write-Host -ForegroundColor Red "Fail: Type Authorization is No." -InformationVariable Test42Info
    $Test42Result = "FAIL"
    $FailCount++
} else {
    Write-Host -ForegroundColor Red "Fail: Type Authorization is not in an expected value." -InformationVariable Test42Info
    Write-Host -ForegroundColor Red "Type Auth Value: "$TypeAuthorization
    $Test42Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 43: Highest System Data Classification"
Write-Host ""

if ($null -eq $classification){
    Write-Host -ForegroundColor Red "Fail: Classification not provided." -InformationVariable Test43Info
    $Test43Result = "FAIL"
    $FailCount++
} else {
    Write-Host -ForegroundColor Cyan "The highest system classification is: "$classification -InformationVariable Test43Info
    $Test43Result = "PASS"
    $PassCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 44: 'RMF Activity' identifies current RMF phase"
Write-Host ""

if ($null -eq $RMFActivity){
    Write-Host -ForegroundColor Red "Fail: RMF Phase Not provided." -InformationVariable Test44Info
    $Test44Result = "FAIL"
    $FailCount++
} else {
    Write-Host -ForegroundColor Green "The RMF Phase is: "$RMFActivity -InformationVariable Test44Info
    Write-Host -ForegroundColor Yellow "Verify this information is Correct."
    $Test44Result = "PASS"
    $PassCount++
}

Write-Host ""
Write-host -ForegroundColor Cyan "Test 47: Security Review field(s) answered"
Write-Host ""

$SecurityReviewReq = $systemdata | Select-Object -ExpandProperty securityReviewRequired
$SecurityReviewCompleted = $systemdata | Select-Object -ExpandProperty securityReviewCompleted
$SecurityReviewDate = $systemdata | Select-Object -ExpandProperty securityReviewCompletionDate
$NextSecurityReviewDate = $systemdata | Select-Object -ExpandProperty nextSecurityReviewDueDate


#make security review date human readable.
$SecurityReviewDate2 = $origin.AddSeconds($NextSecurityReviewDate)
$SecurityReviewDate3 = ($SecurityReviewDate2).ToString("yyyy-MM-dd")

#calculate if security review is within one year. 
$SecurityReviewDateDiff = $NextSecurityReviewDate - $SecurityReviewDate


if ($null -eq $SecurityReviewReq -or $null -eq $SecurityReviewCompleted -or $null -eq $SecurityReviewDate -or $null -eq $NextSecurityReviewDate) {
    Write-Host -ForegroundColor Red "FAIL: Security Review Information is missing incomplete." -InformationVariable Test47Info
    Write-Host -ForegroundColor Red "Security Review Required: "        $SecurityReviewReq
    Write-Host -ForegroundColor Red "Security Review Completed: "       $SecurityReviewCompleted
    Write-Host -ForegroundColor Red "Security Review Completion Date: " $SecurityReviewDate
    Write-Host -ForegroundColor Red "Next Security Review Date: "       $NextSecurityReviewDate
    $Test47Result = "FAIL"
    $FailCount++

} elseif ($SecurityReviewReq -like "True") {
    if ($SecurityReviewCompleted -like "True") {
        if ($SecurityReviewDateDiff -gt "31536000") {
            Write-Host -ForegroundColor Red "FAIL: Next Security Review date is greater than one year since previous review: "$SecurityReviewDate3 -InformationVariable Test47Info
            $Test47Result = "FAIL"
            $FailCount++
        } else {
            Write-Host -ForegroundColor Green "PASS: Security Review equals yes, Security Review Completed and dated within one year." -InformationVariable Test47Info
            $Test47Result = "PASS"
            $PassCount++
        }
    } else {
        Write-Host -ForegroundColor Red "FAIL: Security Review has not been completed" -InformationVariable Test47Info
        $Test47Result = "FAIL"
        $FailCount++
    }
} else {
    Write-Host -ForegroundColor Red "FAIL: Security Review Required is not set to YES" -InformationVariable Test47Info
    $Test47Result = "FAIL"
    $FailCount++
} 




Write-Host ""
Write-host -ForegroundColor Cyan "Test 48: Contingency Plan field(s) answered"
Write-Host ""

$contingencyPlanRequired = $systemdata | Select-Object -ExpandProperty contingencyPlanRequired
$contingencyPlanArtifact = $systemdata | Select-Object -ExpandProperty contingencyPlanArtifact
$contingencyPlanTested = $systemdata | Select-Object -ExpandProperty contingencyPlanTested
$contingencyPlanTestDate = $systemdata | Select-Object -ExpandProperty contingencyPlanTestDate

$contingencyPlanDateDiff = $TodayDate - $contingencyPlanTestDate


if ($null -eq $contingencyPlanRequired -or $null -eq $contingencyPlanArtifact -or $null -eq $contingencyPlanTested -or $null -eq $contingencyPlanTestDate) {
    Write-Host -ForegroundColor Red "FAIL: Contingency Plan information is missing Information is missing incomplete or no Artifact." -InformationVariable Test48Info
    Write-Host -ForegroundColor Red "Contingency Plan Required: "   $contingencyPlanRequired
    Write-Host -ForegroundColor Red "Contingency Plan Artifact: "   $contingencyPlanArtifact
    Write-Host -ForegroundColor Red "Contingency Plan Tested: "     $contingencyPlanTested
    Write-Host -ForegroundColor Red "Next Security Test Date: "     $contingencyPlanTestDate
    $Test48Result = "FAIL"
    $FailCount++

} elseif ($contingencyPlanRequired -like "True") {
    if ($contingencyPlanTested -like "True") {
        if ($contingencyPlanDateDiff -gt "31536000") {
            Write-Host -ForegroundColor Red "FAIL: Contingency Plan test is greater than one year old." -InformationVariable Test48Info
            $Test48Result = "FAIL"
            $FailCount++
        } else {
            Write-Host -ForegroundColor Green "PASS: Contingency Plan is required, artifact uploaded, Tested within this year." -InformationVariable Test48Info
            $Test48Result = "PASS"
            $PassCount++
        }
    } else {
        Write-Host -ForegroundColor Red "FAIL: Contingency Plan has not been tested." -InformationVariable Test48Info
        $Test48Result = "FAIL"
        $FailCount++
    }
} else {
    Write-Host -ForegroundColor Red "FAIL: Contingency Plan Required is not set to YES" -InformationVariable Test48Info
    $Test48Result = "FAIL"
    $FailCount++
} 

<#
Test 49: Incident Response Plan field(s) answered
#>

Write-Host ""
Write-host -ForegroundColor Cyan "Test 49: Incident Response Plan field(s) answered"
Write-Host ""

$incidentResponsePlanRequired = $systemdata | Select-Object -ExpandProperty incidentResponsePlanRequired
$incidentResponsePlanArtifact = $systemdata | Select-Object -ExpandProperty incidentResponsePlanArtifact

$incidentArtifact = $ArtifactDetailsData | Where-Object {$_.filename -like "$incidentResponsePlanArtifact"}
$incidentArtifactdate = $incidentArtifact | Select-Object -ExpandProperty "Last Reviewed"

if ($incidentResponsePlanRequired -like "True") {
    if (($null -eq $incidentResponsePlanArtifact -or $null -eq $incidentArtifactdate) -or ($incidentArtifactdate -le $OneYearAgoEpoch)) {
        Write-Host -ForegroundColor Red "FAIL: The Incident Response Plan requires is Yes, but the Artifact is missing or older than one Year" -InformationVariable Test49Info
        $test49Result = "FAIL"
        $FailCount++
    } else {
        Write-Host -ForegroundColor Green "PASS: The Incident Response Artifact is Present and current: "$incidentResponsePlanArtifact -InformationVariable Test49Info
        $test49Result = "PASS"
        $PassCount++
    }
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: Incident response required is No, verify this is correct. " -InformationVariable Test49Info
    $test49Result = "CONCERN"
    $ConcernCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 51: Disaster Recovery Plan"
Write-Host ""

$disasterRecoveryPlanRequired = $systemdata | Select-Object -ExpandProperty disasterRecoveryPlanRequired
$disasterRecoveryPlanArtifact = $systemdata | Select-Object -ExpandProperty disasterRecoveryPlanArtifact

$DisasterArtifact = $ArtifactDetailsData | Where-Object {$_.filename -like "$disasterRecoveryPlanArtifact"}
$DisasterArtifactdate = $DisasterArtifact | Select-Object -ExpandProperty "Last Reviewed"

if ($null -eq $disasterRecoveryPlanRequired) {
    Write-Host -ForegroundColor Red "FAIL: Disaster Recovery plan required is not defined" -InformationVariable Test51Info
    $test51Result = "FAIL"
    $FailCount++
} elseif ($disasterRecoveryPlanRequired -like "False") {
    Write-Host -ForegroundColor Yellow "CONCERN: Disaster Recovery Plan required is set to No, verify this is correct." -InformationVariable Test51Info
    $test51Result = "CONCERN"
    $ConcernCount++
} else {
    if (($null -eq $disasterRecoveryPlanArtifact -or $null -eq $DisasterArtifactdate) -or ($DisasterArtifactdate -le $OneYearAgoEpoch)) {
        Write-Host -ForegroundColor Red "FAIL: Disaster Recovery Plan is required but artifact is not provided or older than one year." -InformationVariable Test51Info
        $test51Result = "FAIL"
        $FailCount++
    } else {
        Write-Host -ForegroundColor Green "PASS: Disaster Recovery Plan Required is Yes and Artifact is current: "$disasterRecoveryPlanArtifact -InformationVariable Test51Info
        $test51Result = "PASS"
        $PassCount++
    }
}



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 52: Privacy Impact Assessment field(s) answered"
Write-Host ""

# grab the single data object
$entry = $systemdata

# safe-extract each property (or $null if missing)
if ($entry.PSObject.Properties.Name -contains 'privacyImpactAssessmentRequired') {
    $privacyImpactAssessmentRequired = $entry.privacyImpactAssessmentRequired
} else {
    $privacyImpactAssessmentRequired = $null
}
if ($entry.PSObject.Properties.Name -contains 'privacyImpactAssessmentDate') {
    $privacyImpactAssessmentDate = $entry.privacyImpactAssessmentDate
} else {
    $privacyImpactAssessmentDate = $null
}
if ($entry.PSObject.Properties.Name -contains 'privacyImpactAssessmentArtifact') {
    $privacyImpactAssessmentArtifact = $entry.privacyImpactAssessmentArtifact
} else {
    $privacyImpactAssessmentArtifact = $null
}

# compute age in seconds (assuming $TodayDate is a [DateTime])
if ($privacyImpactAssessmentDate) {
    $privacyImpactAssessmentDateDiff = ($TodayDate - $privacyImpactAssessmentDate).TotalSeconds
} else {
    $privacyImpactAssessmentDateDiff = $null
}

if (-not $privacyImpactAssessmentRequired) {
    Write-Host -ForegroundColor Red "FAIL: Privacy Impact Assessment information is missing" -InformationVariable Test52Info
    $Test52Result = "FAIL"; $FailCount++
}
elseif ($privacyImpactAssessmentRequired -eq $false) {
    if ($NSS -eq $false) {
        Write-Host -ForegroundColor Red "FAIL: Privacy Impact Assessment Required is NO and system is not NSS." -InformationVariable Test52Info
        $Test52Result = "FAIL"; $FailCount++
    } else {
        Write-Host -ForegroundColor Gray "N/A: PIA is not required for NSS systems" -InformationVariable Test52Info
        $Test52Result = "N/A"; $NACount++
    }
}
else {
    # required == $true
    if (-not $privacyImpactAssessmentArtifact) {
        Write-Host -ForegroundColor Red "FAIL: PIA is required but no Artifact provided" -InformationVariable Test52Info
        $Test52Result = "FAIL"; $FailCount++
    }
    elseif (-not $privacyImpactAssessmentDate) {
        Write-Host -ForegroundColor Red "FAIL: PIA artifact uploaded, but date not provided" -InformationVariable Test52Info
        $Test52Result = "FAIL"; $FailCount++
    }
    elseif ($privacyImpactAssessmentDateDiff -gt (3 * 365 * 24 * 3600)) {
        Write-Host -ForegroundColor Red "FAIL: PIA document is older than three years" -InformationVariable Test52Info
        $Test52Result = "FAIL"; $FailCount++
    }
    else {
        Write-Host -ForegroundColor Green "PASS: PIA uploaded and date is within three years: $privacyImpactAssessmentArtifact" `
            -InformationVariable Test52Info
        $Test52Result = "PASS"; $PassCount++
    }
}




Write-Host ""
Write-host -ForegroundColor Cyan "Test 53: Privacy Act SORN"
Write-Host ""

$SORN = $systemdata | Select-Object -ExpandProperty privacyActSystemOfRecordsNoticeRequired

if ($null -eq $SORN -or $SORN -like "-") {
    Write-Host -ForegroundColor Red "FAIL: Privacy Act SORN question is not answered." -InformationVariable Test53Info
    $Test53Result = "FAIL"
    $FailCount++ 
} else {
    Write-Host -ForegroundColor Green "PASS: Privacy Act SORN question is: "$SORN -InformationVariable Test53Info
    $Test53Result = "PASS"
    $PassCount++ 
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 54: E-Authentication Risk Assessment field(s) answered"
Write-Host ""

$eAuthenticationRiskAssessmentRequired = $systemdata | Select-Object -ExpandProperty eAuthenticationRiskAssessmentRequired
$eAuthenticationRiskAssessmentArtifact = $systemdata | Select-Object -ExpandProperty eAuthenticationRiskAssessmentArtifact
$dataeAuthCompleteDate = $dataReport[0]."Risk Assessment Comp Plan Date"

if ($null -eq $eAuthenticationRiskAssessmentRequired) {
    Write-Host -ForegroundColor Red "FAIL: E-Authentication Risk Assesment question is not answered" -InformationVariable Test54Info
    $Test54Result = "FAIL"
    $FailCount++
} elseif ($eAuthenticationRiskAssessmentRequired -like "True") {
    if ($null -eq $eAuthenticationRiskAssessmentArtifact) {
        Write-Host -ForegroundColor Red "FAIL: E-Auth Risk Assessment is Yes, but no artifact is provided" -InformationVariable Test54Info
        $Test54Result = "FAIL"
        $FailCount++
    } elseif ($null -eq $dataeAuthCompleteDate) {
        Write-Host -ForegroundColor Red "FAIL: data eAuthentication field was blank or could not be verified." -InformationVariable Test54Info
        $Test54Result = "FAIL"
        $FailCount++
    } else {
        Write-Host -ForegroundColor Green "PASS: E-Auth Risk Assesment required is Yes, and the Artifact name is: "$eAuthenticationRiskAssessmentArtifact -InformationVariable Test54Info
        $Test54Result = "PASS"
        $PassCount++
    }
} elseif ($eAuthenticationRiskAssessmentRequired -like "False") {
    Write-Host -ForegroundColor Green "PASS: E-Auth Risk Assesment Required is No." -InformationVariable Test54Info
    $Test54Result = "PASS"
    $PassCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 55: Mission Criticality' matches data *If Assess Only, System Mission Criticality allows for Assess Only*"
Write-Host ""

$dataMissionCrit = $dataReport[0]."Mission Criticality"
$MissionCriticality = $systemdata | Select-Object -ExpandProperty missionCriticality

#translate eMASS data to match data
if ($MissionCriticality -like "Mission Support (MS)") {
    $MissionCriticality2 = "MS"
} elseif ($MissionCriticality -like "Mission Essential (ME)") {
    $MissionCriticality2 = "ME"
} elseif ($MissionCriticality -like "Mission Critical (MC)") {
    $MissionCriticality2 = "MC"
} 

if ($MissionCriticality2 -like $dataMissionCrit) {
    if ($MissionCriticality2 -like "MC" -and $RegistrationType -like "Assess Only") {
        Write-Host -ForegroundColor Red "FAIL: data and eMASS match, but system cannot be Assess only and Mission Critical." -InformationVariable Test55Info
        $Test55Result = "FAIL"
        $FailCount++
    } elseif ($MissionCriticality2 -like "ME" -and $RegistrationType -like "Assess Only") {
        if ($confidentiality -like "Low" -and $integrity -like "Low" -and $availability -like "Low"){
            Write-Host -ForegroundColor Green "PASS: data and eMASS match and Mission Criticality is correct" -InformationVariable Test55Info
            $Test55Result = "PASS"
            $PassCount++
        } else {
            Write-Host -ForegroundColor Red "FAIL: data and eMASS match, but system cannot be Assess only with provided criticality levels." -InformationVariable Test55Info
            $Test55Result = "FAIL"
            $FailCount++
        }
    } elseif ($MissionCriticality2 -like "MS" -and $RegistrationType -like "Assess Only") {
        if ($confidentiality -like "High" -and $integrity -like "High" -and $availability -like "High" -or $SystemType -like "*Major Application*") {
            Write-Host -ForegroundColor Red "FAIL: data and eMASS match, but system cannot be Assess only with provided criticality levels." -InformationVariable Test55Info
            $Test55Result = "FAIL"
            $FailCount++
        } else {
            Write-Host -ForegroundColor Green "PASS: data and eMASS match and Mission Criticality is correct" -InformationVariable Test55Info
            $Test55Result = "PASS"
            $PassCount++
        }
    } else {
        Write-Host -ForegroundColor Green "PASS: data and eMASS match and Mission Criticality is correct" -InformationVariable Test55Info
        $Test55Result = "PASS"
        $PassCount++
    }
} else {
    Write-Host -ForegroundColor Red "Fail: data mission criticality does not match eMASS" -InformationVariable Test55Info
    Write-Host -ForegroundColor Red "data:  "$dataMissionCrit
    Write-Host -ForegroundColor Red "eMASS: "$MissionCriticality
    $Test55Result = "FAIL"
    $FailCount++
}

<#
Test 56: 'Governing Mission Area' matches data 'System Mission Area'
#>

Write-Host ""
Write-host -ForegroundColor Cyan "Test 56: Governing Mission Area matches data System Mission Area"
Write-Host ""

$governingMissionArea = $systemdata | Select-Object -ExpandProperty governingMissionArea
$dataMissionArea = $dataReport[0]."Mission Area"

#translate eMASS data to match data
if ($governingMissionArea -like "Enterprise Information Environment MA (EIEMA)"){
    $governingMissionArea2 = "EIEMA"
} elseif ($governingMissionArea -like "Business MA (BMA)") {
    $governingMissionArea2 = "BMA"
} elseif ($governingMissionArea -like "Warfighting MA (WMA)") {
    $governingMissionArea2 = "WMA"
} elseif ($governingMissionArea -like "DoD portion of the Intelligence MA (DIMA)") {
    $governingMissionArea2 = "DIMA"
}

if ($dataMissionArea -like $governingMissionArea2) {
    Write-Host -ForegroundColor Green "PASS: eMASS and data Mission Areas match." -InformationVariable Test56Info
    $Test56Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: eMASS and data Mission Areas do not match." -InformationVariable Test56Info
    $Test56Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 57: Acquisition Category matches data"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: This test is unable to run due to a report issue with data, please verify manualy." -InformationVariable Test57Info
$Test57Result = "CONCERN"
$ConcernCount++



Write-Host ""
Write-host -ForegroundColor Cyan "Test 58: Software Category' matches data *Assess Only*"
Write-Host ""

if ($RegistrationType -like "Assess Only") {
    Write-Host -ForegroundColor Yellow "CONCERN: eMASS and data data fields do not support automatic matching for this test." -InformationVariable Test58Info
    $Test58Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Gray "N/A: System is not assess only" -InformationVariable Test58Info
    $Test58Result = "N/A"
    $NACount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 59: Acquisition Category matches data"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: This test is unable to run due to a report issue with data, please verify manualy." -InformationVariable Test59Info
$Test59Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-host -ForegroundColor Cyan "Test 60: All External Security Services (ESS) Fields Addressed"
Write-Host ""



Write-Host -ForegroundColor Yellow "CONCERN: The eMASS API does not have data for this test." -InformationVariable Test60Info
$Test60Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-host -ForegroundColor Cyan "Test 61: Connection point(s) details provided if applicable"
Write-Host ""

$ConnectionPoints = $systemdata | Select-Object -ExpandProperty connectivityCcsd
$CCSD = $ConnectionPoints | Select-Object -ExcludeProperty ccsdNumber

if ($null -eq $ConnectionPoints) {
    Write-Host -ForegroundColor Red "FAIL: No connection points are provided." -InformationVariable Test61Info
    $Test61Result = "FAIL"
    $FailCount++
} else {
    if ($null -eq $CCSD) {
        Write-Host -ForegroundColor Yellow "CONCERN: Connetion points provided, but no CCSD number provided" -InformationVariable Test61Info
        $Test61Result = "CONCERN"
        $ConcernCount++
    } else {
        Write-Host -ForegroundColor Green "PASS: Connection points are provided, a manual check is needed." -InformationVariable Test61Info
        Write-Host -ForegroundColor Yellow "Connnection Points: "$ConnectionPoints
        $Test61Result = "PASS"
        $PassCount++
    }
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 62: All ATC/IATC Fields Addressed (if applicable)"
Write-Host ""

$ATCDecision =      $SystemDetailsSorted | Select-Object -ExpandProperty "ATC Decision"
$ATCDecisionDate =  $SystemDetailsSorted | Select-Object -ExpandProperty "ATC Decision Date"
$ATCTermDate =      $SystemDetailsSorted | Select-Object -ExpandProperty "ATC Termination Date"


if ($null -eq $ATCDecision -or
    $null -eq $ATCDecisionDate -or
    $null -eq $ATCTermDate) {
        Write-Host -ForegroundColor Yellow "CONCERN: No ATC/IATC information provided, if applicable" -InformationVariable Test62Info
        $Test62Result = "CONCERN"
        $ConcernCount++ 
} else {
    Write-Host -ForegroundColor Green "PASS: ATC/IATC fields are provided." $ATCDecision $ATCDecisionDate $ATCTermDate -InformationVariable Test62Info
    $Test62Result = "PASS"
    $PassCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 63: Applied Information Types Matches Information Type Survey (ITS) Evidence Artifact"
Write-Host ""

$ITSArtifact = $ArtifactDetailsData | Where-Object {$_.'Category' -eq "Information Type" -and $_.'Filename' -like "*.msg"}
$ITSArtifactNAME = $ITSArtifact | Select-Object -ExpandProperty Filename
$ITSArtifactFILE = $ITSArtifact | Select-Object -ExpandProperty "Artifact Name"


if ($null -eq $ITSArtifact) {
    Write-Host -ForegroundColor Red "FAIL: ITS Artifact is not found" -InformationVariable Test63Info
    $Test63Result = "FAIL"
    $FailCount++

} else {
    Write-Host -ForegroundColor Green "PASS: ITS Artifact was found: "$ITSArtifactNAME -InformationVariable Test63Info
    Write-Host -ForegroundColor Green "Filename: "$ITSArtifactFILE
    $Test63Result = "PASS"
    $PassCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 64: Applied Information Types Matches Information Type Survey (ITS) Evidence Artifact"
Write-Host ""


if ($null -eq $ITSArtifact) {
    Write-Host -ForegroundColor Red "FAIL: ITS Artifact is not found" -InformationVariable Test64Info
    $Test64Result = "FAIL"
    $FailCount++

} else {
    Write-Host -ForegroundColor Green "PASS: ITS Artifact was found: "$ITSArtifactNAME -InformationVariable Test64Info
    Write-Host -ForegroundColor Green "Filename: "$ITSArtifactFILE
    $Test64Result = "PASS"
    $PassCount++
}




Write-Host ""
Write-host -ForegroundColor Cyan "Test 65: 'Impact Level' Identified"
Write-Host ""

if ($null -eq $impact) {
    Write-Host -ForegroundColor Red "Fail: System Impact Level is not provided" -InformationVariable Test65Info
    $Test65Result = "FAIL"
    $FailCount++
} elseif ($impact -like "Low") {
    if ($confidentiality -like "Low" -and $integrity -like "Low" -and $availability -like "Low") {
        Write-Host -ForegroundColor Green "PASS: Impact Level is correctly Assigned" -InformationVariable Test65Info
        $Test65Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: Impact Level does not Match CIA values." -InformationVariable Test65Info
        Write-Host -ForegroundColor Red "Confidentiality: "$confidentiality
        Write-Host -ForegroundColor Red "Integrity: "$integrity
        Write-Host -ForegroundColor Red "Availability: "$availability
        $Test65Result = "FAIL"
        $FailCount++
    }
} elseif ($impact -like "Moderate") {
    if ($confidentiality -like "moderate" -or $integrity -like "moderate" -or $availability -like "moderate" -or $confidentiality -notlike "High" -or $integrity -notlike "High" -or $availability -notlike "High") {
        Write-Host -ForegroundColor Green "PASS: Impact Level is correctly Assigned" -InformationVariable Test65Info
        $Test65Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: Impact Level does not Match CIA values." -InformationVariable Test65Info
        Write-Host -ForegroundColor Red "Confidentiality: "$confidentiality
        Write-Host -ForegroundColor Red "Integrity: "$integrity
        Write-Host -ForegroundColor Red "Availability: "$availability
        $Test65Result = "FAIL"
        $FailCount++
    }
} elseif ($impact -like "High") {
    if ($confidentiality -like "High" -or $integrity -like "High" -or $availability -like "High") {
        Write-Host -ForegroundColor Green "PASS: Impact Level is correctly Assigned" -InformationVariable Test65Info
        $Test65Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: Impact Level does not Match CIA values." -InformationVariable Test65Info
        Write-Host -ForegroundColor Red "Confidentiality: "$confidentiality
        Write-Host -ForegroundColor Red "Integrity: "$integrity
        Write-Host -ForegroundColor Red "Availability: "$availability
        $Test65Result = "FAIL"
        $FailCount++
    }
} else {
    Write-Host -ForegroundColor Red "FAIL: Impact Level is not in an expected value." -InformationVariable Test65Info
    $Test65Result = "FAIL"
    $FailCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 66: Information Type Evidence Artifact Linked"
Write-Host ""

$ITSArtifactFail = $ArtifactDetailsData | Where-Object {$_.'Category' -eq "Information Type" -and $_.'Filename' -like "*.xlsx"}


if ($null -eq $ITSArtifactFail) {

if ($null -eq $ITSArtifact) {
    Write-Host -ForegroundColor Red "FAIL: ITS Artifact is not found" -InformationVariable Test66Info
    $Test66Result = "FAIL"
    $FailCount++

} else {
    Write-Host -ForegroundColor Green "PASS: ITS Artifact was found: "$ITSArtifactNAME -InformationVariable Test66Info
    Write-Host -ForegroundColor Green "Filename: "$ITSArtifactFILE
    $Test66Result = "PASS"
    $PassCount++
}
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: Information Type Artifact is an excel file, which means it might not be approved. "$ITSArtifactFail.filename -InformationVariable Test66Info
    $Test66Result = "CONCERN"
    $ConcernCount++ 
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 67: Are any Overlays applied to the system and have all Overlay questions been answered?"
Write-Host ""

#Pull Privacy Data
$Privacydata = Get-Content (join-path $DemoAssets "Privacy.json") | ConvertFrom-Json
$PrivacydataSorted = $Privacydata.data | Where-Object {$_.'System ID' -eq $SystemID} 

$PrivacyOverlayQuestions = $PrivacydataSorted | Select-Object -ExpandProperty "Privacy Overlays Responses"

$Overlays = $SystemDetailsSorted | Select-Object -ExpandProperty "Applied Overlays"

#pull data information
$datafinancialFeeder = $dataReport[0]."Accounting System or Financial Feeder System"

$OverallResult = $true  # Assume PASS initially
$OverlayInfoLine = $null # Initialize info line


if ($null -eq $Overlays) {

    $OverallResult = $false
    $OverlayInfoLine += "Overlay data missing. "

} elseif ($Overlays -like "-") {

    $OverallResult = $true
    $OverlayInfoLine += "No overlays applied, verify this is correct."    
}

if ($PII -like "True" -or $PHI -like "True") {

    if ($Overlays -like "*Privacy*") {
        if ($null -eq $PrivacyOverlayQuestions) {
            $OverallResult = $false
            $OverlayInfoLine += "Privacy overlay questions missing. "

        } elseif ($PrivacyOverlayQuestions -like "*-*") {
            $OverallResult = $false
            $OverlayInfoLine += "Privacy overlay questions unanswered. "

        } else {
            if ($PrivacyOverlayQuestions -like "*Does the Exception of the Business Rolodex Information Apply? (Yes)*") {
                $OverallResult = $false
                $OverlayInfoLine += "Unauthorized Rolodex exemption. "
            }
        }
    } else {
        $OverallResult = $false
        $OverlayInfoLine += "Privacy overlay missing for PII/PHI. "
    }
}

if ($FinancialManagementSystem -like "True") {
    if ($Overlays -like "*Financial Management*") {
        #Pass - no action needed
    } else {
        $OverallResult = $false
        $OverlayInfoLine += "Financial Management overlay missing. "
    }
}

if ($datafinancialFeeder -like "Yes") {
    if ($Overlays -like "*Financial Management*") {
        #Pass - no action needed
    } else {
        $OverallResult = $false
        $OverlayInfoLine += "data indicates financial feeder system, but FMS overlay is not applied. "
    }
}


if ($null -eq $OverlayInfoLine) {
    $OverallResult = $true
    $OverlayInfoLine = "Verify the applied overlays are correct: $Overlays"
}

# Final Result Output
if ($OverallResult) {
    Write-Host -ForegroundColor Green "PASS: "$OverlayInfoLine -InformationVariable test67Info
    $Test67Result = "PASS"
} else {
    Write-Host -ForegroundColor Red "FAIL: "$OverlayInfoLine -InformationVariable Test67Info
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 68: Were controls added or subtracted due to an overlay or manual tailoring?"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: Identify if controls have been added or subtracted via manual tailoring." -InformationVariable Test68Info
$Test68Result = "CONCERN"
$ConcernCount++



Write-Host ""
Write-host -ForegroundColor Cyan "Test 69: Have 'STIGS/SRGs' been identified for all security relevant Hardware, Software and functions as validated against, HW/SW List and Module, Diagrams, ACAS Scans & Other relevant system information?"
Write-Host ""

$AppliedSTIGS = $systemdata | Select-Object -ExpandProperty appliedStigs

if ($null -eq $AppliedSTIGS) {
    Write-Host -ForegroundColor Yellow "CONCERN: No Stig data was found." -InformationVariable Test69Info
    $Test69Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: The following STIGs are applied, manual verification is needed: "$AppliedSTIGS -InformationVariable Test69Info
    $Test69Result = "CONCERN"
    $ConcernCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 70: Recommended Added Controls are addressed?"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test70Info
$Test70Result = "CONCERN"
$ConcernCount++




Write-Host ""
Write-host -ForegroundColor Cyan "Test 71: Does system have any significant changes since last Authorization?"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test71Info
$Test71Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-host -ForegroundColor Cyan "Test 72: All 14 ATC Critical Controls are in the system Baseline and have test results in eMASS that are less than 1 yr old?"
Write-Host ""

#list of ATC Critical Controls
$controlinfo = Get-Content (join-path $DemoAssets "TestResults.json") | ConvertFrom-Json

$controlinfodata = $controlinfo.data | Where-Object {
    $_.control -like "AC-17" -or
    $_.control -like "AC-17(2)" -or
    $_.control -like "IA-2(1)" -or
    $_.control -like "IA-2(2)" -or
    $_.control -like "IA-2(3)" -or
    $_.control -like "IA-2(4)" -or
    $_.control -like "IA-5(1)" -or
    $_.control -like "IR-8" -or
    $_.control -like "IR-9" -or
    $_.control -like "RA-5" -or
    $_.control -like "SC-7" -or
    $_.control -like "SC-8" -or
    $_.control -like "SC-28" -or
    $_.control -like "SI-2"
}


$Untested14Controls = $null

if ($null -eq $controlinfodata) {
    Write-Host -ForegroundColor Red "FAIL: No Controls Test data was returned" -InformationVariable Test72Info
    $Test72Result = "FAIL"
    $FailCount++
} else {
    foreach ($ATTest in $controlinfodata) {
        if (($ATTest.testdate -le $OneYearAgoEpoch) -or ($ATTest.testdate -eq "[REDACTED]") -or ($null -eq $ATTest.testdate) -or ($ATTest.complianceStatus -like "Non-Compliant") ) {
            $Untested14Controls += $ATTest.acronym
            }
    }

    if ($null -eq $Untested14Controls) {
        Write-Host -ForegroundColor Green "PASS: All 14 ATC Critical Controls have been tested within the past year." -InformationVariable Test72Info
        $Test72Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: One or more of the 14 ATC Critical Controls, has not been tested within one year, are noncompliant, or could not be verified: "$Untested14Controls -InformationVariable Test72Info
        $Test72Result = "FAIL"
        $FailCount++
    }
}   



Write-Host ""
Write-host -ForegroundColor Cyan "Test 73: All Controls/APs/CCIs 1. have been assessed and 2. have a current Test Result in eMASS that are less than 1 yr old? Controls cannot have a status of incomplete or Unassessed (UA)."
Write-Host ""

Write-Host ""
Write-host -ForegroundColor Cyan "Test 73: All Controls/APs/CCIs 1. have been assessed and 2. have a current Test Result in eMASS that are less than 1 yr old? Controls cannot have a status of incomplete or Unassessed (UA)."
Write-Host ""

if ($ATOStatus -like "*Authorization to Operate*") {

    $TestResultsFull = Get-Content (join-path $DemoAssets "TestResults.json") | ConvertFrom-Json
    $TestResultsFullData = $TestResultsFull.data

    $FailedControls = $null

    foreach ($TestResult in $TestResultsFullData) {
        if (($TestResult.testdate -le $OneYearAgoEpoch) -or ($TestResult.testdate -eq "[REDACTED]") -or ($null -eq $TestResult.testdate) -or ($TestResult.complianceStatus -like "Non-Compliant") ) {
            $FailedControls += $ATTest.acronym 
            }
    }

    if ($null -eq $FailedControls) {
        Write-Host -ForegroundColor Green "PASS: All Controls have been tested within the past year." -InformationVariable Test73Info
        $Test73Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: One or more of the Controls, has not been tested within one year, are noncompliant, or could not be verified: "$FailedControls -InformationVariable Test73Info
        $Test73Result = "FAIL"
        $FailCount++
    }

} else {
    Write-Host -ForegroundColor Gray "Not Applicable: System is not in ATO Phase" -InformationVariable Test72Info
    $Test72Result = "N/A"
    $NACount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 74: All controls have a status of Official or Validated? Exception with those with traceability through a POA&M"
Write-Host ""

$CACDataFull = Get-Content (join-path $DemoAssets "CAC.json") | ConvertFrom-Json
$CACData = $CACDataFull.data

$FailedCACControls = $null

foreach ($CAC in $CACData) {
    if ($CAC.complianceStatus -like "Non-Compliant") {
        $FailedCACControls += $CAC.controlAcronym 
        }
}

if ($null -eq $FailedCACControls) {
    Write-Host -ForegroundColor Green "PASS: All Controls are compliant or not applicable. Verification needed to determine if its official." -InformationVariable Test74Info
    $Test74Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the Controls are noncompliant, or could not be verified: "$FailedCACControls -InformationVariable Test74Info
    $Test74Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 75: Are any Non-Compliant package controls flagged as Critical (Red Diamond)?"
Write-Host ""

if ($ATOStatus -like "*Authorization to Operate*") {
    #list of ATC Critical Controls
    $criticalcontrolinfo = Get-Content (join-path $DemoAssets "TestResults.json") | ConvertFrom-Json

    $criticalcontrolinfodatafiltered = $criticalcontrolinfo.data | Where-Object {
        $_.control -like "AC-17" -or
        $_.control -like "AC-17(2)" -or
        $_.control -like "IA-2(1)" -or
        $_.control -like "IA-2(2)" -or
        $_.control -like "IA-2(3)" -or
        $_.control -like "IA-2(4)" -or
        $_.control -like "IA-5(1)" -or
        $_.control -like "IR-8" -or
        $_.control -like "IR-9" -or
        $_.control -like "RA-5" -or
        $_.control -like "SC-7" -or
        $_.control -like "SC-8" -or
        $_.control -like "SC-28" -or
        $_.control -like "SI-2" -or
        $_.control -like "AC-2" -or
        $_.control -like "AC-3" -or
        $_.control -like "AC-4" -or
        $_.control -like "AC-5" -or
        $_.control -like "AC-6" -or
        $_.control -like "AC-6(9)" -or
        $_.control -like "AC-7" -or
        $_.control -like "AC-9" -or
        $_.control -like "AC-10" -or
        $_.control -like "AC-11" -or
        $_.control -like "AC-12" -or
        $_.control -like "AC-18" -or
        $_.control -like "AC-19" -or
        $_.control -like "AC-20" -or
        $_.control -like "AC-24" -or
        $_.control -like "AC-25" -or
        $_.control -like "AU-3" -or
        $_.control -like "AU-4" -or
        $_.control -like "AU-5" -or
        $_.control -like "AU-6" -or
        $_.control -like "AU-9" -or
        $_.control -like "AU-10" -or
        $_.control -like "AU-13" -or
        $_.control -like "AU-14" -or
        $_.control -like "AU-16" -or
        $_.control -like "CM-6" -or
        $_.control -like "CM-7" -or
        $_.control -like "CM-7(1)" -or
        $_.control -like "CM-8" -or
        $_.control -like "CM-10" -or
        $_.control -like "IA-5" -or
        $_.control -like "IR-6" -or
        $_.control -like "PL-8" -or
        $_.control -like "SA-22" -or
        $_.control -like "SI-3" -or
        $_.control -like "SI-4" -or
        $_.control -like "SI-4(4)" -or
        $_.control -like "SI-4(5)"
    }
    
    

    #set varible to empty before use
    $FailedFiftyControls = $null

    foreach ($Control2 in $criticalcontrolinfodatafiltered) {
        if ($Control2.complianceStatus -like "Non-Compliant") {
            $FailedFiftyControls += $Control2.controlAcronym
        }
    }

    if ($null -eq $FailedFiftyControls) {
        Write-Host -ForegroundColor Green "PASS: All Critical Controls are compliant or not applicable. Verification needed to determine if its official." -InformationVariable Test75Info
        $Test75Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: One or more of the Critical Controls are noncompliant, or could not be verified: "$FailedFiftyControls -InformationVariable Test75Info
        $Test75Result = "FAIL"
        $FailCount++
    }

} else {

    Write-Host -ForegroundColor Gray "Not Applicable: System is not in ATO Phase" -InformationVariable Test75Info
    $Test75Result = "N/A"
    $NACount++

}





Write-Host ""
Write-host -ForegroundColor Cyan "Test 76: Not Applicable CCIs have valid justification for status. *Existing or Expired ATO ONLY*?"
Write-Host ""

if ($ATOStatus -like "*Authorization to Operate*") {
    
    $NACCIcontrols = $null

    foreach ($TestResult2 in $TestResultsFullData) {
        if ($TestResult2.complianceStatus -like "Not Applicable") {
            $NACCIcontrols += $TestResult2.cci
        }
    }

    if ($null -eq $NACCIcontrols){
        Write-Host -ForegroundColor Green "PASS: All CCIs are applicable. Verification needed to determine if its official." -InformationVariable Test76Info
        $Test76Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Yellow "CONCERN: One or more of the CCIs are not applicable, or could not be verified, verify valid status: "$FailedFiftyControls -InformationVariable Test76Info
        $Test76Result = "CONCERN"
        $ConcernCount++
    }

} else {
    Write-Host -ForegroundColor Gray "Not Applicable: System is not in Post ATO Phase" -InformationVariable Test76Info
    $Test76Result = "N/A"
    $NACount++
}

<#
Test 77 has been Removed. 
#>



Write-Host ""
Write-host -ForegroundColor Cyan "Test 78: SLCM [ConMon] strategy [for all Controls including Red Critical and FISMA controls], correlation and analysis activities, and response actions are documented and associated to CA-7."
Write-Host ""


if ($ATOStatus -like "*Authorization to Operate*") {

    $SLCMBlankControl = @()
  

    foreach ($control2 in $ControlsData2) {
        if (($control2.implementationStatus -like "Implemented" -or $control2.implementationStatus -like "Planned" -or $control2.implementationStatus -like "Not Applicable") -and 
            (($null -eq $control2.slcmCriticality -or $control2.slcmCriticality -like "Undetermined") -or 
            ($null -eq $control2.slcmFrequency -or $control2.slcmFrequency -like "Undetermined") -or 
            ($null -eq $control2.slcmMethod -or $control2.slcmMethod -like "Undetermined") -or 
            ($null -eq $control2.slcmReporting -or $control2.slcmReporting -like "Undetermined") -or 
            ($null -eq $control2.slcmTracking -or $control2.slcmTracking -like "Undetermined") -or 
            ($null -eq $control2.slcmComments -or $control2.slcmComments -like "Undetermined"))) {
            $SLCMBlankControl += $control2.acronym
        }
    }

    


    if ($null -eq $SLCMBlankControl) {
        Write-Host -ForegroundColor Green "PASS: All Controls have SLCM information provided. Verification needed to determine if its official." -InformationVariable Test78Info
        $Test78Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: One or more of the Controls have a atatus of Implemented, Planned, or Not applicable and have blank SLCM information: "$SLCMBlankControl -InformationVariable Test78Info
        $Test78Result = "FAIL"
        $FailCount++
    }

} else {

    Write-Host -ForegroundColor Gray "Not Applicable: System is not in Post ATO Phase" -InformationVariable Test78Info
    $Test78Result = "N/A"
    $NACount++

}

Write-Host ""
Write-host -ForegroundColor Cyan "Test 79: Incident Response Plan provided as an artifact for IR-8 and evidence of most recent IR Test provided in IR-3."
Write-Host ""


$incidentArtifact = $ArtifactDetailsData | Where-Object {$_.filename -like "$incidentResponsePlanArtifact"}
$incidentArtifactdate = $incidentArtifact | Select-Object -ExpandProperty "Last Reviewed"


if ($ATOStatus -like "*Authorization to Operate*") {

    if (($null -eq $incidentResponsePlanArtifact -or $null -eq $incidentArtifactdate) -or ($incidentArtifactdate -le $OneYearAgoEpoch)) {
        Write-Host -ForegroundColor Red "FAIL: The incident response plan is either missing or has not been reviewed/tested within one year." -InformationVariable Test79Info
        $Test79Result = "FAIL"
        $FailCount++
    } else {
        Write-Host -ForegroundColor Green "PASS: The incident response plan is present and within one year: "$incidentResponsePlanArtifact -InformationVariable Test79Info
        $Test79Result = "PASS"
        $PassCount++
}

} else {

    Write-Host -ForegroundColor Gray "Not Applicable: System is not in Post ATO Phase" -InformationVariable Test79Info
    $Test79Result = "N/A"
    $NACount++

}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 80: For Assess Only packages where there is scannable Hardware and Software is RA-5 in the baseline?"
Write-Host ""


$RA5 = $ControlsData2 | Where-Object {$_.acronym -like "RA-5"}

if ($RA5.includedStatus -like "Baseline") {
    Write-Host -ForegroundColor Green "PASS: Control RA-5 is included in the baseline." -InformationVariable Test80Info
    $Test80Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: Control RA-5 is not in the baseline or could not be verified." -InformationVariable Test80Info
    $Test80Result = "FAIL"
    $FailCount++
}




Write-Host ""
Write-host -ForegroundColor Cyan "Test 81: For Assess Only packages where CSSP inheritance cannot be established and no CSSP artifact is present, have the following controls been addressed (cannot be N/A)? AC-2.9, AC-2.18 , SA-5.10, SA-11.4, SA-11.8, SC-5.1, SI-2.2, SI-2.4."
Write-Host ""

if($RegistrationType -like "Assess and Authorize"){

    Write-Host -ForegroundColor Gray "Not Applicable: System is not Assess only" -InformationVariable Test81Info
    $Test81Result = "N/A"
    $NACount++

} else {
    
    $AssessOnlyControlsinfo = Get-Content (join-path $DemoAssets "TestResults.json") | ConvertFrom-Json
    $AssessOnlyControlsinfodata = $AssessOnlyControlsinfo.data | Where-Object {
        $_.control -like "AC-2.9" -or
        $_.control -like "AC-2.18" -or
        $_.control -like "SA-5.10" -or
        $_.control -like "SA-11.4" -or
        $_.control -like "SA-11.8" -or
        $_.control -like "SC-5.1" -or
        $_.control -like "SI-2.2" -or
        $_.control -like "SI-2.4"
    }
    
    
    $AssessOnlyFailedControls = $null

    foreach ($AssessOnlyControl in $AssessOnlyControlsinfodata) {
        if ($AssessOnlyControl.complianceStatus -like "Not Applicable" ) {
            $AssessOnlyFailedControls += $AssessOnlyControl.controlAcronym 
            }
    }


    if ($null -eq $AssessOnlyFailedControls) {
        Write-Host -ForegroundColor Green "PASS: All Required controls for Assess only are part of the baseline." -InformationVariable Test81Info
        $Test81Result = "PASS"
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: One or more of the required Controls are not applicable: "$AssessOnlyFailedControls -InformationVariable Test81Info
        $Test81Result = "FAIL"
        $FailCount++
    }

}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 82: 'Compliant' Controls have 'Implemented' or 'Inherited' Implementation Status"
Write-Host ""


$compliantControls = $ControlsData2 | Where-Object {$_.complianceStatus -like "C"}

$compliantControlsNotImplemented = $null

foreach ($compliantControl in $compliantControls) {
    if ($compliantControl.implementationStatus -like "Implemented" -or $compliantControl.implementationStatus -like "Inherited") {
        
    } else {
        $compliantControlsNotImplemented += $compliantControl.acronym
    }
}

if ($null -eq $compliantControlsNotImplemented) {
    Write-Host -ForegroundColor Green "PASS: All compliant controls are implemented or inherited." -InformationVariable Test82Info
    $Test82Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the controls are compliant but not implemented or inherited: "$compliantControlsNotImplemented -InformationVariable Test82Info
    $Test82Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 83: 'Non-Compliant' Controls have 'Planned' or Not Implemented Implementation Status"
Write-Host ""

$noncompliantControls2 = $ControlsData2 | Where-Object {$_.complianceStatus -like "NC"}

$noncompliantControlImplemented = $null

foreach ($noncompliant in $noncompliantControls2) {
    if ($noncompliant.implementationStatus -like "Planned" -or $noncompliant.implementationStatus -like "Not Implemented" ) {
         
    } else {
        $noncompliantControlImplemented += $noncompliant.acronym
    }
}

if ($null -eq $noncompliantControlImplemented) {
    Write-Host -ForegroundColor Green "PASS: All non compliant controls are planned or not implemented." -InformationVariable Test83Info
    $Test83Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the non compliant controls are not in a correct status: "$noncompliantControlImplemented -InformationVariable Test83Info
    $Test83Result = "FAIL"
    $FailCount++
}




Write-Host ""
Write-host -ForegroundColor Cyan "Test 83: Estimated Completion Date' (ECD) is in the future for Control's with 'Planned' Implementation Status; ECD is current or is in the past for Controls with 'Compliant' Implementation Status; ECD is 'blank' for Controls with 'Not Applicable' Implementation Status."
Write-Host ""

$NAControls =       $ControlsData2 | Where-Object {$_.complianceStatus -like "NA"}
$PlannedControls =  $ControlsData2 | Where-Object {$_.implementationStatus -like "Planned"}

$compliantControlWrongDate = $null 
foreach ($compliantControl in $compliantControls) {
    if ($compliantControl.estimatedCompletionDate -ge $TodayDate) {
        $compliantControlWrongDate += $compliantControl.acronym
    } 
}

$NAControlsWrongDate = $null
foreach ($NAControl in $NAControls) {
    if ($null -eq $NAControl.estimatedCompletionDate) {
        
    } else {
        $NAControlsWrongDate += $NAControl.acronym
    }
}

$PlannedControlsWrongDate = $null 
foreach ($PlannedControl in $PlannedControls) {
    if ($PlannedControl.estimatedCompletionDate -le $TodayDate) {
        $PlannedControlsWrongDate += $PlannedControl.acronym
    }
}

if ($null -eq $compliantControlWrongDate -or $null -eq $NAControlsWrongDate -or $null -eq $PlannedControlsWrongDate) {
    Write-Host -ForegroundColor Green "PASS: All Estimated completion dates are within expected tolerances." -InformationVariable Test84Info
    $Test84Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more estimated completion dates are not correct for the listed controls: "$compliantControlWrongDate $NAControlsWrongDate $PlannedControlsWrongDate -InformationVariable Test84Info
    $Test84Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 85: 'Not Applicable' Controls have 'Not Applicable' or 'Inherited' Implementation Status"
Write-Host ""

$NAControlsWrongStatus = $Null
foreach ($NAControl in $NAControls) {
    if ($NAControl.implementationStatus -like "Not Applicable" -or $NAControl.implementationStatus -like "Inherited") {
        
    } else {
        $NAControlsWrongStatus += $NAControl.acronym
    }
}

if ($null -eq $NAControlsWrongStatus) {
    Write-Host -ForegroundColor Green "PASS: All Not Applicable controls are in the correct status." -InformationVariable Test85Info
    $Test85Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the non applicable controls are not in a correct status: "$NAControlsWrongStatus -InformationVariable Test85Info
    $Test85Result = "FAIL"
    $FailCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 86: Completed Risk Assessment"
Write-Host ""

$noncompliantControls2 = $ControlsData2 | Where-Object {$_.complianceStatus -like "NC"}

$controlsnoriskAssessment = $null 

foreach ($BadControl in $noncompliantControls2) {
    if ($null -eq $BadControl.vulnerabilitySummary -or $null -eq $BadControl.mitigations -or $null -eq $BadControl.impactDescription -or $null -eq $BadControl.recommendations) {
        $controlsnoriskAssessment += $BadControl.acronym
    }
}

if ($null -eq $controlsnoriskAssessment) {
    Write-Host -ForegroundColor Green "PASS: All Non Compliant Controls have a completed risk assessment." -InformationVariable Test86Info
    $Test86Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the Non Compliant Controls do not have a completed risk assesment: "$controlsnoriskAssessment -InformationVariable Test86Info
    $Test86Result = "FAIL"
    $FailCount++
}




Write-Host ""
Write-Host -ForegroundColor Cyan "Test 87: ATC Specific controls that are Not Compliant have a Risk Assessment Summary entry"
Write-Host ""

$fiftycontrolsNC = $ControlsData2 | Where-Object {$_.acronym -in $FiftyControlsArray -and $_.complianceStatus -like "NC"}

$fiftycontrolsNCnoRiskAssesment = $null

foreach ($badcontrol2 in $fiftycontrolsNC) {
    if ($null -eq $BadControl2.vulnerabilitySummary -or $null -eq $BadControl2.mitigations -or $null -eq $BadControl2.impactDescription -or $null -eq $BadControl2.recommendations) {
        $fiftycontrolsNCnoRiskAssesment += $badcontrol2.acronym
    }
}

if ($null -eq $fiftycontrolsNCnoRiskAssesment) {
    Write-Host -ForegroundColor Green "PASS: All Non Compliant Controls have a completed risk assessment." -InformationVariable Test87Info
    $Test87Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the Non Compliant Controls do not have a completed risk assesment: "$controlsnoriskAssessment -InformationVariable Test87Info
    $Test87Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 88: Non-Compliant' Controls:  Vulnerability Summary, Impact Description, and Recommendations have a response"
Write-Host ""

if ($null -eq $controlsnoriskAssessment) {
    Write-Host -ForegroundColor Green "PASS: All Non Compliant Controls have a completed risk assessment." -InformationVariable Test88Info
    $Test88Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the Non Compliant Controls do not have a completed risk assesment: "$controlsnoriskAssessment -InformationVariable Test88Info
    $Test88Result = "FAIL"
    $FailCount++
}


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 89: Compliant' Controls:  Vulnerability Summary, Impact Description, and Recommendations have been removed"
Write-Host ""

$compliantControls2 = $ControlsData2 | Where-Object {$_.complianceStatus -like "C"}

$goodcontrolswithRisk = $null 

foreach ($goodcontrol in $compliantControls2) {
    if ($null -eq $goodControl.vulnerabilitySummary -and $null -eq $goodControl.mitigations -and $null -eq $goodControl.impactDescription -and $null -eq $goodControl.recommendations) {
        
    } else {
        $goodcontrolswithRisk += $ControlsData2.acronym
    }
}

if ($null -eq $goodcontrolswithRisk) {
    Write-Host -ForegroundColor Green "PASS: All Compliant Controls have a blank risk assessment." -InformationVariable Test89Info
    $Test89Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the Compliant Controls have risk assesment information: "$goodcontrolswithRisk -InformationVariable Test89Info
    $Test89Result = "FAIL"
    $FailCount++
}


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 90: Not Applicable' Controls: Vulnerability Summary, Impact Description, and Recommendations have been removed"
Write-Host ""

$NAControls2 = $ControlsData2 | Where-Object {$_.complianceStatus -like "NA"}

$NAcontrolsWithRisk = $null

foreach ($NAcontrol in $NAControls2) {
    if ($null -eq $NAcontrol.vulnerabilitySummary -and $null -eq $NAcontrol.mitigations -and $null -eq $NAcontrol.impactDescription -and $null -eq $NAcontrol.recommendations) {
        
    } else {
        $NAcontrolsWithRisk += $NAControl.acronym
    }
}

if ($null -eq $NAcontrolsWithRisk) {
    Write-Host -ForegroundColor Green "PASS: All Not Applicable Controls have a blank risk assessment." -InformationVariable Test90Info
    $Test90Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the Not Applicable Controls have risk assesment information: "$NAcontrolsWithRisk -InformationVariable Test90Info
    $Test90Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 91: Common Control Provider identified for inherited controls & correct Security Control Designation listed?"
Write-Host ""

$inheritedcontrolwithoutCCP = $null

foreach ($control4 in $ControlsData2) {
    if ($control4.isInherited -eq $true -and ($null -eq $control4.commonControlProvider -or $control4.commonControlProvider -like "-")) {
        $inheritedcontrolwithoutCCP += $control4.acronym
    }
}

if ($null -eq $inheritedcontrolwithoutCCP) {
    Write-Host -ForegroundColor Green "PASS: All inherited controls have common control providers." -InformationVariable Test91Info
    $Test91Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the inherited controls do not have a valid common control provider: "$inheritedcontrolwithoutCCP -InformationVariable Test91Info
    $Test91Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 92: Implementation Narrative"
Write-Host ""

$controlsNotImplemented = $null

foreach ($control3 in $ControlsData2) {
    if ($null -eq $control3.implementationNarrative -and $control3.complianceStatus -like "C") {
        $controlsNotImplemented += $control3.acronym
    }
}

if ($null -eq $controlsNotImplemented) {
    Write-Host -ForegroundColor Green "PASS: All compliant controls have an implementation narritive." -InformationVariable Test92Info
    $Test92Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the compliant controls are missing an implementation narritive: "$controlsNotImplemented -InformationVariable Test92Info
    $Test92Result = "FAIL"
    $FailCount++
}




Write-Host ""
Write-Host -ForegroundColor Cyan "Test 93: Responsible Entities"
Write-Host ""


$controlsNotImplementedexceptNA = $null

foreach ($control3 in $ControlsData2) {
    if ($null -eq $control3.implementationNarrative -and $control3.complianceStatus -notlike "NA") {
        $controlsNotImplementedexceptNA += $control3.acronym
    }
}

if ($null -eq $controlsNotImplementedexceptNA) {
    Write-Host -ForegroundColor Green "PASS: All controls exept N/A have an implementation narritive." -InformationVariable Test93Info
    $Test93Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the controls except N/A are missing an implementation narritive: "$controlsNotImplemented -InformationVariable Test93Info
    $Test93Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 94: Risk Attribute for Impact Description matches system categorization C-I-A impact level"
Write-Host ""

$NCcontrolImpactMismatch = $null

foreach ($NCcontrol in $noncompliantControls2) {
    if ($NCcontrol.impact -like $impact) {
        
    } else {
        $NCcontrolImpactMismatch += $NCcontrol.acronym 
    }
}

if ($null -eq $NCcontrolImpactMismatch) {
    Write-Host -ForegroundColor Green "PASS: All non-compliant controls have Impact that matches the System." -InformationVariable Test94Info
    $Test94Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the non compliant controls have an impact that is missing or does not match the system: "$NCcontrolImpactMismatch -InformationVariable Test94Info
    $Test94Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 95: All Risk Attributes are populated and do not deviate from Recommended values without documentation and support for change."
Write-Host ""

$BadControlsNoRiskLevel = $null

foreach ($badcontrol3 in $noncompliantControls2) {
    if ($null -eq $badcontrol3.Severity -or $null -eq $badcontrol3.relevanceOfThreat -or $null -eq $badcontrol3.likelihood -or $null -eq $badcontrol3.impact -or $null -eq $badcontrol3.residualRiskLevel) {
        $BadControlsNoRiskLevel += $badcontrol3.acronym
    }
}

if ($null -eq $BadControlsNoRiskLevel) {
    Write-Host -ForegroundColor Green "PASS: All non-compliant controls have risk levels." -InformationVariable Test95Info
    $Test95Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the non compliant controls are missing risk assessment: "$NAcontrolsWithRisk -InformationVariable Test95Info
    $Test95Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 96: Are any controls showing up passing inheritance through the system?"
Write-Host ""


Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test96Info
$Test96Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 97: There are no 'Enter Non-Compliant Test Results for Compliant APs' suggested actions"
Write-Host -ForegroundColor Cyan "This test takes several minutes."
Write-Host ""

$compliantControlsTestMismatch = @()

foreach ($compliantControl in $compliantControls) {
    foreach ($testresult3 in $TestResultsFullData) {
        if ($testresult3.complianceStatus -like "Non-Compliant" -and $testresult3.control -like $compliantControl.acronym) {
            $compliantControlsTestMismatch += $compliantControl.acronym
        }
    }
}

$compliantControlsTestMismatchCount = $compliantControlsTestMismatch | Measure-Object | Select-Object -ExpandProperty Count

if ($null -eq $compliantControlsTestMismatch) {
    Write-Host -ForegroundColor Yellow "CONCERN: All Compliant Controls have compliant test results. Manual Checking is needed." -InformationVariable Test97Info
    $Test97Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the compliant controls have test results that are not compliant: "$compliantControlsTestMismatchCount -InformationVariable Test97Info
    $Test97Result = "FAIL"
    $FailCount++
}


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 98: Are all errors cleared?"
Write-Host ""

$errorsTestResults = $null

foreach ($testresultcheck in $TestResultsFullData) {
    
    $testControlID = $testresultcheck.control

    $controltoCheck = $ControlsData2 | Where-Object {$_.acronym -like $testControlID}

    if ($testresultcheck.complianceStatus -like "Compliant" -and $controltoCheck."complianceStatus" -like "C") {
        
    } elseif ($testresultcheck.complianceStatus -like "Non-Compliant" -and $controltoCheck."complianceStatus" -like "NC") {
        
    } elseif ($testresultcheck.complianceStatus -like "Non-Compliant" -and $controltoCheck."complianceStatus" -like "C") {
        $errorsTestResults += $testresultcheck.control
    } elseif ($testresultcheck.complianceStatus -like "Compliant" -and $controltoCheck."complianceStatus" -like "NC") {
        $errorsTestResults += $testresultcheck.control
    }
}

if ($null -eq $errorsTestResults) {
    Write-Host -ForegroundColor Yellow "CONCERN: All Errors in Test Results and Controls are cleared. Manually Verify" -InformationVariable Test98Info
    $Test98Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the test results and control compliance results are in conflict: "$errorsTestResults -InformationVariable Test98Info
    $Test98Result = "FAIL"
    $FailCount++
}


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 99: There are no 'Conflicted Findings"
Write-Host ""

#this test is essentially a duplicate of 98. 
if ($null -eq $errorsTestResults) {
    Write-Host -ForegroundColor Green "PASS: All Errors in Test Results and Controls are cleared." -InformationVariable Test99Info
    $Test99Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: One or more of the test results and control compliance results are in conflict: "$errorsTestResults -InformationVariable Test99Info
    $Test99Result = "FAIL"
    $FailCount++
}


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 100: There are no Unmapped Findings"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test100Info
$Test100Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 101: Does record contain benchmark technical data?"
Write-Host ""


    Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test101Info
    $Test101Result = "CONCERN"
    $ConcernCount++




Write-Host ""
Write-Host -ForegroundColor Cyan "Test 102: Are STIGs imported for every STIG applied in Categorization module? Existing or Expired ATO ONLY"
Write-Host ""


    Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test102Info
    $Test102Result = "CONCERN"
    $ConcernCount++




Write-Host ""
Write-Host -ForegroundColor Cyan "Test 103: Are STIGS imported that are not documented as a requirement? Existing or Expired ATO ONLY"
Write-Host ""


    Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test103Info
    $Test103Result = "CONCERN"
    $ConcernCount++


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 104: Does the record contain current STIG/SRG technical data and are all applicable STIGs/SRGs current IAW the DISA Version | Release?"
Write-Host ""


Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test104Info
$Test104Result = "CONCERN"
$ConcernCount++

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 106: ACAS scans for 100% of the devices within the last 30 days or IAW any AO approved exceptions as required by TASKORD 20-0020."
Write-Host ""

try {
    # Gather scan findings
    $FindingsRaw      = Get-Content (join-path $DemoAssets "Findings.json") | ConvertFrom-Json
    $FindingsFiltered = $FindingsRaw.data | Where-Object { $_."System ID" -eq $systemID }

    # Filter for ACAS scans
    $ACASscansexist = $FindingsFiltered | Where-Object { $_."Scan Type" -like "*ACAS*" }

    if (-not $ACASscansexist) {
        Write-Host -ForegroundColor Red "FAIL: No ACAS scan data has been found." -InformationVariable Test106Info
        $Test106Result = "FAIL"
        $FailCount++
    }
    else {
        # Date threshold
        $ThirtyDaysAgo = (Get-Date).AddDays(-30)
        $ThirtyDaysAgoEpoch = (New-TimeSpan -Start (Get-Date "01/01/1970") -End $ThirtyDaysAgo).TotalSeconds

        $oldScans = @()
        foreach ($finding in $ACASscansexist) {
            $scanDate = $finding."Last Scan Date"
            if ($null -eq $scanDate -or
                $scanDate -like "-" -or
                [double]$scanDate -lt $ThirtyDaysAgoEpoch) {

                $oldScans += $finding.hostname
            }
        }

        if ($oldScans.Count -eq 0) {
            Write-Host -ForegroundColor Green "PASS: All ACAS scans are within 30 days." -InformationVariable Test106Info
            $Test106Result = "PASS"
            $PassCount++
        }
        else {
            Write-Host -ForegroundColor Red "FAIL: $($oldScans.Count) device(s) lack recent ACAS scans: $($oldScans -join ', ')" -InformationVariable Test106Info
            $Test106Result = "FAIL"
            $FailCount++
        }
    }
}
catch {
    Write-Host -ForegroundColor Red "FAIL: Unable to complete Test 106 due to API error: $($_.Exception.Message)" -InformationVariable Test106Info
    $Test106Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 108: Any vulnerability that remains open past 30 days from the first observed date has an associated POA&M with mitigations sufficient to lower the risk of the vulnerability"
Write-Host ""



#gathering POAM Details
$POAMDetailsRaw = Get-Content (join-path $DemoAssets "SystemPOAMDashboard.json") | ConvertFrom-Json
$POAMDetailsFiltered = $POAMDetailsRaw.data | Where-Object {$_."System ID" -eq $systemID}

$FindingsWithoutPOAM = $null

foreach ($Finding in $FindingsFiltered) {
    foreach ($POAM3 in $POAMDetailsFiltered) {
          if ($Finding."Security Check" -like $POAM3."Security Checks") {
            
          } else {
            $FindingsWithoutPOAM += $Finding."Security Check"
          }
        } 
    }


if ($null -eq $FindingsWithoutPOAM) {
    Write-Host -ForegroundColor Green "PASS: No Vulnerabilities have been found greater than 30 Days with no POAM" -InformationVariable Test108Info
    $Test108Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: The following Findings are greater than 30 days old and do not have a POAM: "$FindingsWithoutPOAM -InformationVariable Test108Info
    $Test108Result = "FAIL"
    $FailCount++
}



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 109: Any Government Developed, GOTS or Open Source Software being authorized via this eMASS package requires Code analysis."
Write-Host ""

#gathering Software Details information
$SoftwareDetailsRaw = Get-Content (join-path $DemoAssets "SoftwareDetailsDashboard.json") | ConvertFrom-Json
$SoftwareDetailsFiltered = $SoftwareDetailsRaw.data | Where-Object {$_."System ID" -eq $systemID}

$ControlGOTSData = $null
$GOTSArtifacts = $null

foreach ($Title in $SoftwareDetailsFiltered) {
    if ($Title."Software Type" -like "*GOTS*" -or
        $Title."Software Type" -like "GOTS Application" -or
        $Title."Software Type" -like "GOTS - Application" -or
        $Title."Software Type" -like "GOTS - Application" -or
        $Title."Software Type" -like "GOTS Software" -or
        $Title."Software Type" -like "Open Source Software" -or
        $Title."Software Type" -like "*Open Source*" -or
        $Title."Software Type" -like "*OSS*") {
        $GOTSArtifacts += $Title.'Software Name'
            foreach ($Control5 in $ControlsData2) {
                if (($control5.acronym -like "SA-11(1)" -or $control5.acronym -like "SA-11(8)" -or $control5.acronym -like "SI-2") -and $control5."implementationStatus" -like "Implemented") {
                    $ControlGOTSData += $control5.acronym
                }
            } 
        
    } 
}

if ($null -eq $ControlGOTSData -and $null -eq $GOTSArtifacts) {
    Write-Host -ForegroundColor Gray "N/A: System does not identify any GOTS or Open Source Software" -InformationVariable Test109Info
    $Test109Result = "N/A"
    $NACount++
} elseif ($null -eq $ControlGOTSData -and $null -ne $GOTSArtifacts) {
    Write-Host -ForegroundColor Red "FAIL: GOTS or Open Source Software exists but Important Controls may be missing." -InformationVariable Test109Info
    $Test109Result = "FAIL"
    $FailCount++
} elseif ($null -ne $ControlGOTSData -and $null -ne $GOTSArtifacts) {
    Write-Host -ForegroundColor Yellow "CONCERN: GOTS or Open Source Software has been identified and a correct control had been identified. Manual Verification Needed" -InformationVariable Test109Info
    $Test109Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: GOTS or Open Source Software is not in an expected state." -InformationVariable Test109Info
    $Test109Result = "CONCERN"
    $ConcernCount++
}



#this is a bridge code from two different authors with different varibles used. 
$HardwareDetailsRaw = Get-Content (join-path $DemoAssets "HardwareDetailsDashboard.json") | ConvertFrom-Json
$HardwareDetailsFiltered = $HardwareDetailsRaw.data | Where-Object {$_."System ID" -eq $systemID}

$systemHWDetailsdata = $HardwareDetailsFiltered

$systemSWDetailsdata = $SoftwareDetailsFiltered


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 110: Checking traceability between Resources Module and HW/SW Lists"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test110Info
$Test110Result = "CONCERN"
$ConcernCount++



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 111: ''Component Type', 'Machine Name', 'IP Address' (if applicable), 'Virtual Asset', 'Manufacturer', 'Model Number', 'Serial Number' (if applicable), 'OS/iOS/FW Version', 'Location' provided for each component listed"
Write-Host ""

# Initialize test result
$Test111Result = "PASS"

# Initialize tracking for incomplete assets
$incompleteAssets = @()

# Iterate through each asset in the system data
foreach ($asset in $systemHWDetailsdata) {
    # Check if any required fields are missing or empty
    $missingFields = @()

    if (-not $asset."Component Type" -or $asset."Component Type" -eq "-") { $missingFields += "Component Type" }
    if (-not $asset."Asset Name" -or $asset."Asset Name" -eq "-") { $missingFields += "Machine Name" }
    if (-not $asset."Asset IP Address" -or $asset."Asset IP Address" -eq "-") { $missingFields += "IP Address" }
    if (-not $asset."Virtual Asset" -or $asset."Virtual Asset" -eq "-") { $missingFields += "Virtual Asset" }
    if (-not $asset."Manufacturer" -or $asset."Manufacturer" -eq "-") { $missingFields += "Manufacturer" }
    if (-not $asset."Model Number" -or $asset."Model Number" -eq "-") { $missingFields += "Model Number" }
    if (-not $asset."Serial Number" -or $asset."Serial Number" -eq "-") { $missingFields += "Serial Number" }
    if (-not $asset."OS/iOS/FW Version" -or $asset."OS/iOS/FW Version" -eq "-") { $missingFields += "OS/iOS/FW Version" }
    if (-not $asset."Location" -or $asset."Location" -eq "-") { $missingFields += "Location" }

    # If any required field is missing, log the asset
    if ($missingFields.Count -gt 0) {
        $Test111Result = "FAIL"
        $incompleteAssets += "$($asset.'Asset Name') (ID: $($asset.'System ID')) missing: $($missingFields -join ', ')"
    }
}

# Output results in one line
if ($Test111Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: All hardware components have the required fields populated." -InformationVariable Test111Info
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: Missing fields in Assets → $($incompleteAssets -join ' | ')" -InformationVariable Test111Info
    $FailCount++
}



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 112: All component types listed appear in the 'System Authorization Boundary' Artifact"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test112Info
$Test112Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 113: All OS/iOS/FW versions listed on the 'System Authorization Boundary' Artifact are present and match 'Software Name' and 'Version'"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test113Info
$Test113Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 114: Ensure POC Data is Identified for Hardware"
Write-Host ""

# Initialize test result
$Test114Result = "PASS"

# Initialize tracking variable
$assetsMissingPOC = @()

# Iterate through each asset in systemHWDetailsdata
foreach ($asset in $systemHWDetailsdata.data) {
    # Check if POC fields are missing or empty
    $missingPOCFields = @()

    if (-not $asset.'POC Office/Organization' -or $asset.'POC Office/Organization' -eq "-") { $missingPOCFields += "POC Office/Organization" }
    if (-not $asset.'POC First Name' -or $asset.'POC First Name' -eq "-") { $missingPOCFields += "POC First Name" }
    if (-not $asset.'POC Last Name' -or $asset.'POC Last Name' -eq "-") { $missingPOCFields += "POC Last Name" }
    if (-not $asset.'POC Phone Number' -or $asset.'POC Phone Number' -eq "-") { $missingPOCFields += "POC Phone Number" }
    if (-not $asset.'POC Email' -or $asset.'POC Email' -eq "-") { $missingPOCFields += "POC Email" }
    if ($null -eq $asset.'Date Reviewed / Updated' -or $asset.'Date Reviewed / Updated' -le $OneYearAgoEpoch) {$missingPOCFields += "Review Date Over One Year"}

    # If any required POC field is missing, log the asset
    if ($missingPOCFields.Count -gt 0) {
        $Test114Result = "FAIL"
        $assetsMissingPOC += "$($asset.'Asset Name') (ID: $($asset.'System ID')) missing: $($missingPOCFields -join ', ')"
    }
}

# Output results
if ($Test114Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: All hardware components have POC details populated." -InformationVariable Test114Info
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: Missing POC fields or obselete review date in Assets → $(($assetsMissingPOC -join ' | '))" -InformationVariable Test114Info
    $FailCount++
}





Write-Host ""
Write-Host -ForegroundColor Cyan "Test 115: Is there a POA&M for End of Life Hardware inside the authorization boundary?"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test115Info
$Test115Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 116: Software Type', 'Software Vendor', 'Software Name', and 'Software Version' provided for each software listed"
Write-Host ""

# Initialize test result
$Test116Result = "PASS"

# Initialize tracking variable
$missingSoftwareEntries = @()

# Iterate through each software entry in systemSWDetailsdata
foreach ($software in $systemSWDetailsdata) {
    # Check for missing required fields
    $missingFields = @()

    if (-not $software.'Software Type' -or $software.'Software Type' -eq "-") { $missingFields += "Software Type" }
    if (-not $software.'Software Vendor' -or $software.'Software Vendor' -eq "-") { $missingFields += "Software Vendor" }
    if (-not $software.'Software Name' -or $software.'Software Name' -eq "-") { $missingFields += "Software Name" }
    if (-not $software.'Software Version' -or $software.'Software Version' -eq "-") { $missingFields += "Software Version" }

    # If any required field is missing, log the software entry
    if ($missingFields.Count -gt 0) {
        $Test116Result = "FAIL"
        $missingSoftwareEntries += "$($software.'Software Name') (ID: $($software.'System ID')) missing: $($missingFields -join ', ')"
    }
}

# Output results
if ($Test116Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: All software entries have the required fields populated." -InformationVariable Test116Info
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: Missing required fields in Software Entries → $(($missingSoftwareEntries -join ' | '))" -InformationVariable Test116Info
    $FailCount++
}


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 117: All Software identified in ACAS scans appear in the Software Baseline"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test117Info
$Test117Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 118: Ensure a POC is Identified for Software"
Write-Host ""

# Initialize test result
$Test118Result = "PASS"

# Initialize tracking variable
$missingPOCFields = @()
$assetsMissingPOC = @()

# Iterate through each software entry in systemSWDetailsdata
foreach ($software in $systemSWDetailsdata) {
    # Check if License POC field is missing or empty
    if (-not $software.'POC Office/Organization' -or $software.'POC Office/Organization' -eq "-") { $missingPOCFields += "POC Office/Organization" }
    if (-not $software.'POC First Name' -or $software.'POC First Name' -eq "-") { $missingPOCFields += "POC First Name" }
    if (-not $software.'POC Last Name' -or $software.'POC Last Name' -eq "-") { $missingPOCFields += "POC Last Name" }
    if (-not $software.'POC Phone Number' -or $software.'POC Phone Number' -eq "-") { $missingPOCFields += "POC Phone Number" }
    if (-not $software.'POC Email' -or $software.'POC Email' -eq "-") { $missingPOCFields += "POC Email" }
    if ($null -eq $software.'Date Reviewed / Updated' -or $software.'Date Reviewed / Updated' -le $OneYearAgoEpoch) {$missingPOCFields += "Review Date Over One Year"}

    # If any required POC field is missing, log the asset
    if ($missingPOCFields.Count -gt 0) {
        $Test114Result = "FAIL"
        $assetsMissingPOC += "$($software.'Asset Name') (ID: $($software.'System ID')) missing: $($missingPOCFields -join ', ')"
    }

}


# Output results
if ($Test118Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: All software entries have a POC identified." -InformationVariable Test118Info
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: Missing Software POC for → $(($assetsMissingPOC -join ' | '))" -InformationVariable Test118Info
    $FailCount++
}


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 119: Is there a POA&M for End of Life Software inside the authorization boundary?"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: eMASS API does not have this information available" -InformationVariable Test119Info
$Test119Result = "CONCERN"
$ConcernCount++




$filteredJArtifactsJsonObject = $ArtifactDetailsData


# =========================[ Function Definition ]=========================
<#
.SYNOPSIS
    Filters JSON data based on multiple "Artifact Name" search terms.

.DESCRIPTION
    This function searches for partial, case-insensitive matches in the "Artifact Name" field of a JSON object that has already been sorted by System ID.

.PARAMETER apiData
    [Object] - A JSON object containing a "data" array of artifacts.
    NOTE: This JSON should already be filtered by "System ID" before calling this function.

.PARAMETER artifactNames
    [String[]] - An array of search terms to match against the "Artifact Name" field.
    This search is case-insensitive and supports partial matches.

.OUTPUTS
    [String] - A JSON string containing all matching records.
    If no matches are found, the function returns `$null`.

.EXAMPLE
    # Define artifact search terms
    $artifactSearchTerms = @("test", "artifact")

    # Call the function
    $filteredArtifacts = Get-ArtifactInfo -apiData $apiResponseJson -artifactNames $artifactSearchTerms

    # Output results
    Write-Host $filteredArtifacts
#>

function Get-ArtifactInfo {
    param(
            [Parameter(Mandatory=$true)]
            [object[]]$apiData,
            [Parameter(Mandatory=$true)]
            [object[]]$artifactNames
    )
    
    foreach ($name in $artifactNames) {
        foreach ($item in $apiData){
            if ($item."Artifact Name" -like "*$name*" -or $item.filename -like "*$name*") {
                $filteredData += $item.filename
            }
        }
    }

    return $filteredData
}


#Start POAM SECTION

$filteredPoamData = $POAMData2

$filteredPoamData2 = $filteredPoamData | Where-Object {$_.isInherited -eq $false}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 120: POC Information provided under 'General POA&M Information'"
Write-Host ""

# Initialize the test result
$Test120 = "PASS"

$failedId = $null

# Iterate through filtered POAM data
foreach ($entry in $filteredPoamData2) {
    if (-not $entry.pocFirstName -or $null -eq $entry.pocFirstName -or $entry.pocFirstName -eq "-" -or $entry.pocFirstName -eq "" -or `
        -not $entry.pocLastName -or $null -eq $entry.pocLastName -or $entry.pocLastName -eq "-" -or $entry.pocLastName -eq "") {
        
        $failedId += $entry.displayPoamId
        $Test120 = "FAIL"
        break
    }
}

# Final test result
if ($Test120 -eq "FAIL") {
    Write-Host "FAIL - Some POC fields are missing in POAM ID: $failedId" -ForegroundColor Red -InformationVariable Test120Info
    $Test120Result = "FAIL"
    $PassCount++
} else {
    Write-Host "PASS - All entries have valid POC information." -ForegroundColor Green -InformationVariable Test120Info
    $Test120Result = "PASS"
    $PassCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 121: ''Point of Contact' information provided in each POA&M record"
Write-Host ""


# Initialize the test result
$Test121 = "PASS"

$failedId = $null

# Iterate through filtered POAM data
foreach ($entry in $filteredPoamData2) {
    if (-not $entry.pocFirstName -or $null -eq $entry.pocFirstName -or $entry.pocFirstName -eq "-" -or $entry.pocFirstName -eq "" -or `
        -not $entry.pocLastName -or $null -eq $entry.pocLastName -or $entry.pocLastName -eq "-" -or $entry.pocLastName -eq "") {
        
        $failedId += $entry.displayPoamId
        $Test121 = "FAIL"
        break
    }
}

# Final test result
if ($Test121 -eq "FAIL") {
    Write-Host "FAIL - Some non inherited POC fields are missing in POAM ID: $failedId" -ForegroundColor Red -InformationVariable Test121Info
    $Test121Result = "FAIL"
    $PassCount++
} else {
    Write-Host "PASS - All non inherited entries have valid POC information." -ForegroundColor Green -InformationVariable Test121Info
    $Test121Result = "PASS"
    $PassCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 122: All POA&M Entries are mapped to the applicable security control"
Write-Host ""


# Initialize the test result
$Test122Result = "PASS"

$failedId = $null

# Iterate through filtered POAM data
foreach ($entry in $filteredPoamData) {
    if (-not $entry.controlAcronym -or $null -eq $entry.controlAcronym -or $entry.controlAcronym -eq "-" -or $entry.controlAcronym -eq "") {
        
        $failedId += $entry.displaypoamId
        $Test122Result = "FAIL"
        break
    }
}

# Final test result
if ($Test122Result -eq "FAIL") {
    Write-Host "TEST RESULT: FAIL - Missing or invalid security control for POAM ID: $failedId" -ForegroundColor Red -InformationVariable Test122Info
    #I know its redundant. I did this to maintain style/maintainability. I thought about being slick then like.. Nah 
    #I want folks to be able to easilly edit/maintain without my tests being too different
    $Test122Result = "FAIL"
    $FailCount++
} else {
    Write-Host "TEST RESULT: PASS - All entries have valid security controls listed for them" -ForegroundColor Green -InformationVariable Test122Info
    $Test122Result = "PASS"
    $PassCount++
}




Write-Host ""
Write-Host -ForegroundColor Cyan "Test 123: POA&M status and control status do not conflict."
Write-Host ""

# Initialize test result
$Test123Result = "PASS"

# Initialize tracking variables
$invalidPoams = @()  # Store POA&Ms that fail the test

$noncompliantControls5 = $ControlsData2 | Where-Object {$_.$control.complianceStatus -like "NC"}

# Iterate through POA&M records
foreach ($entry in $filteredPoamData) {
    # Skip inherited controls
    if ($entry.isInherited -eq $true) {
        continue
    }

    # Extract relevant fields
    $poamStatus = $entry.status
    $controlStatus = $entry.controlAcronym 
    $cci = $entry.cci  # Control Correlation Identifier (CCI)

    # Rule 1: If POA&M is 'Ongoing', control status must be 'Non-Compliant'
    if ($poamStatus -eq "Ongoing" -and ($controlStatus -match "Compliant" -or $cci -match "Compliant")) {
        $Test123Result = "FAIL"
        $invalidPoams += "$($entry.displayPoamId) (Ongoing but Compliant CCI)"
    }

    # Rule 2: If POA&M is 'Ongoing' or 'Risk Accepted', control status should NOT be 'Compliant'
    if (($poamStatus -eq "Ongoing" -or $poamStatus -eq "Risk Accepted") -and ($controlStatus -match "Compliant" -or $cci -match "Compliant")) {
        $Test123Result = "FAIL"
        $invalidPoams += "$($entry.displayPoamId) (Risk Accepted/Ongoing but Compliant)"
    }

}

# Rule 3: Check for Noncompliant Controls without POAMs
# Loop through each FISMA control
foreach ($control6 in $noncompliantControls5) {
    $controlID = $control6.acronym

    # Flag to check if a match is found
    $matchFound = $false

    # Check if this control appears in any POAM record (substring match)
    foreach ($entry in $filteredPoamData) {
        if ($entry.controlAcronym -like "*$controlID*") {
            $matchFound = $true
            break
        }
    }

    if (-not $matchFound) {
        $Test123Result = "FAIL"
        $invalidPoams += "$($entry.displayPoamId) (Non-Compliant Control with no POAM found!)"
    }
}




# Output results
if ($Test123Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: No conflicts between POA&M status and control status." -InformationVariable Test123Info
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: Some POA&Ms have conflicting control statuses or Controls missing POAMs. Affected POA&Ms: $($invalidPoams -join ', ')" -InformationVariable Test123Info
    $FailCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 124: 'Vulnerability Description' describes vulnerability, except for Not Applicable Control POA&Ms"
Write-Host ""


# Initialize the test result
$Test124Result = "PASS"

$failedId = $null


# Iterate through filtered POAM data
foreach ($entry in $filteredPoamData) {
    #exempt the Not applicable controls status from needing a description
    if ($entry.status -eq "Not Applicable"){
        continue
    }
    if (-not $entry.vulnerabilityDescription -or $null -eq $entry.vulnerabilityDescription -or $entry.vulnerabilityDescription -eq "-" -or $entry.vulnerabilityDescription -eq "") {
        
        $failedId += $entry.poamId
        $Test124Result = "FAIL"
        break
    }
}

# Final test result
if ($Test124Result -eq "FAIL") {
    Write-Host "TEST RESULT: FAIL - Missing description for POAM ID: $failedId" -ForegroundColor Red -InformationVariable Test124Info
    #I know its redundant. I did this to maintain style/maintainability.
    $Test124Result = "FAIL"
    $FailCount++
} else {
    Write-Host "TEST RESULT: PASS - All entries have Vulnerability Descriptions" -ForegroundColor Green -InformationVariable Test124Info
    $Test124Result = "PASS"
    $PassCount++
}



Write-Host ""
Write-host -ForegroundColor Cyan "Test 125: Mitigations' entries are specific to the vulnerabilities, reference compliant compensating controls and/or additional protections implemented, and are sufficient to lower the risk of the vulnerability"
Write-Host ""


# Initialize the test result
$Test125Result = "PASS"

$failedId = $null

# Iterate through filtered POAM data
foreach ($entry in $filteredPoamData) {
    # Exempt statuses other than "Ongoing" or "Risk Accepted" from the check
    if ($entry.status -eq "Ongoing" -or $entry.status -eq "Risk Accepted") {
        
        # Check for missing mitigations or "not applicable" (case-insensitive)
        if (-not $entry.mitigations -or $null -eq $entry.mitigations -or $entry.mitigations -eq "-" -or $entry.mitigations -eq "" -or `
            $entry.mitigations -match "(?i)\bnot applicable\b") {
            
            $failedId += $entry.poamId
            $Test125Result = "FAIL"
            break
        }
    } else {
        # Skip entries with statuses that don't require mitigations
        continue
    }
}

# Final test result
if ($Test125Result -eq "FAIL") {
    Write-Host "FAIL: Missing or invalid mitigations for POAM ID: $failedId" -ForegroundColor Red -InformationVariable Test125Info
    #I know its redundant. I did this to maintain style/maintainability.
    $Test125Result = "FAIL"
    $FailCount++
} else {
    Write-Host "Concern: All entries have mitigations, but manual verification is needed." -ForegroundColor Yellow -InformationVariable Test125Info
    $Test125Result = "CONCERN"
    $ConcernCount++
}



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 126: Does 'Severity' match Risk Analysis guidance for 'Ongoing' and 'Risk Accepted' POA&Ms?"
Write-Host ""

# Initialize test result
$Test126Result = "PASS"

# Placeholder for the highest residual risk found
$highestResidualRisk = "Very Low"

# Define risk level order for comparison
$riskLevels = @("Very Low", "Low", "Moderate", "High", "Very High")

# Function to determine if severity is lower than residual risk
function IsSeverityLower($severity, $residualRisk) {
    return ($riskLevels.IndexOf($severity) -lt $riskLevels.IndexOf($residualRisk))
}

# Iterate through POA&M records to find the highest residual risk
foreach ($entry in $filteredPoamData.data) {
    if ($entry.status -in @("Ongoing", "Risk Accepted")) {
        if ($entry.residualRiskLevel -and ($riskLevels.IndexOf($entry.residualRiskLevel) -gt $riskLevels.IndexOf($highestResidualRisk))) {
            $highestResidualRisk = $entry.residualRiskLevel
        }
    }
}

# Initialize tracking variables
$invalidPoams = @()  # Store POA&Ms that fail the test

# Iterate through POA&M records again for validation
foreach ($entry in $filteredPoamData) {
    # Only check POA&Ms that are "Ongoing" or "Risk Accepted"
    if ($entry.status -in @("Ongoing", "Risk Accepted")) {
        $severity = $entry.severity
        $residualRisk = $entry.residualRiskLevel

        # Rule 1: If Severity is blank, use fallback from SCA-V Workbook (not available in this test)
        if (-not $severity -or $severity -eq "") {
            $Test126Result = "FAIL"
            $invalidPoams += "$($entry.poamId) (Severity: NULL, Residual Risk: $residualRisk)"
        }

        # Rule 2: Severity and Residual Risk Level should match
        if ($severity -ne $residualRisk) {
            $Test126Result = "FAIL"
            $invalidPoams += "$($entry.poamId) (Severity: $severity, Residual Risk: $residualRisk)"
        }

        # Rule 3: Severity should not be lower than highest residual risk in workflow
        if (IsSeverityLower($severity, $highestResidualRisk)) {
            $Test126Result = "FAIL"
            $invalidPoams += "$($entry.poamId) (Severity too low: $severity, Expected at least: $highestResidualRisk)"
        }
    }
}

# Output results
if ($Test126Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: All POA&Ms follow Risk Analysis Severity guidance." -InformationVariable Test126Info
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: Some POA&Ms have incorrect severity levels. Affected POA&Ms: $($invalidPoams -join ', ')" -InformationVariable Test126Info
    $FailCount++
}

<#
Test 127: Does 'Relevance of Threat' match Risk Analysis guidance for all POA&M records with 'Status' entries of Ongoing and Risk Accepted? 
#>

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 127: Does 'Relevance of Threat' match Risk Analysis guidance for 'Ongoing' and 'Risk Accepted' POA&Ms?"
Write-Host ""

# Initialize test result
$Test127Result = "PASS"

# Initialize tracking variables
$invalidPoams = @()  # Store POA&Ms that fail the test
$concernPoams = @()  # Store POA&Ms that have missing 'Relevance of Threat'

# Define valid threat relevance levels based on guidance
$validThreatLevels = @("Very Low", "Low", "Moderate", "High", "Very High")

# Iterate through POA&M records
foreach ($entry in $filteredPoamData) {
    # Only check POA&Ms that are "Ongoing" or "Risk Accepted"
    if ($entry.status -in @("Ongoing", "Risk Accepted")) {
        $relevanceOfThreat = $entry.relevanceOfThreat
        $severity = $entry.severity
        $impact = $entry.impact

        # If 'Relevance of Threat' is missing or blank, flag for manual review
        if (-not $relevanceOfThreat -or $relevanceOfThreat -eq "") {
            $Test127Result = "CONCERN"
            $concernPoams += "$($entry.poamId)"
            continue
        }

        # Validate against Risk Analysis Guidance (I just got the threat levels and ensure its something from there)
        if ($relevanceOfThreat -notin $validThreatLevels) {
            $Test127Result = "FAIL"
            $invalidPoams += "$($entry.poamId) (Relevance of Threat: $relevanceOfThreat)"
        }

        # High Water Mark Rule: Ensure Relevance of Threat isn't lower than Severity or Impact
        if ($validThreatLevels.IndexOf($relevanceOfThreat) -lt [math]::Max($validThreatLevels.IndexOf($severity), $validThreatLevels.IndexOf($impact))) {
            $Test127Result = "FAIL"
            $invalidPoams += "$($entry.poamId) (Relevance of Threat too low: $relevanceOfThreat, Expected at least: $severity or $impact)"
        }
    }
}

# Output results
if ($Test127Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: All POA&Ms follow Risk Analysis 'Relevance of Threat' guidance." -InformationVariable Test127Info
    $PassCount++
} elseif ($Test127Result -eq "CONCERN") {
    Write-Host -ForegroundColor Yellow "CONCERN: Some POA&Ms have missing 'Relevance of Threat' values. Manual verification required. $($concernPoams -join ', ')"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: Some POA&Ms have incorrect 'Relevance of Threat' values: $($invalidPoams -join ', ') The Following POA&Ms have missing 'Relevance of Threat' values. Manual verification required for: $($concernPoams -join ', ')" -InformationVariable Test127Info
    $FailCount++
}



<#
Test 128: Does 'Likelihood' match Risk Analysis guidance for all POA&M records with 'Status' entries of Ongoing and Risk Accepted? 
#>
Write-Host ""
Write-Host -ForegroundColor Cyan "Test 128: Does 'Likelihood' match Risk Analysis guidance for 'Ongoing' and 'Risk Accepted' POA&Ms?"
Write-Host ""

# Initialize test result
$Test128Result = "PASS"

# Initialize tracking variables
$invalidPoams = @()  # Store POA&Ms that fail the test
$concernPoams = @()  # Store POA&Ms that have missing 'Likelihood'

# Define valid likelihood levels based on guidance
$validLikelihoodLevels = @("Very Low", "Low", "Moderate", "High", "Very High")

# Iterate through POA&M records
foreach ($entry in $filteredPoamData) {
    # Only check POA&Ms that are "Ongoing" or "Risk Accepted"
    if ($entry.status -in @("Ongoing", "Risk Accepted")) {
        $likelihood = $entry.likelihood
        $relevanceOfThreat = $entry.relevanceOfThreat
        $impact = $entry.impact

        # If 'Likelihood' is missing or blank, flag for manual review
        if (-not $likelihood -or $likelihood -eq "") {
            $Test128Result = "CONCERN"
            $concernPoams += "$($entry.poamId)"
            continue
        }

        # Validate against Risk Analysis Guidance
        if ($likelihood -notin $validLikelihoodLevels) {
            $Test128Result = "FAIL"
            $invalidPoams += "$($entry.poamId) (Likelihood: $likelihood)"
        }

        # High Water Mark Rule: Ensure Likelihood isn't lower than Relevance of Threat or Impact
        if ($validLikelihoodLevels.IndexOf($likelihood) -lt [math]::Max($validLikelihoodLevels.IndexOf($relevanceOfThreat), $validLikelihoodLevels.IndexOf($impact))) {
            $Test128Result = "FAIL"
            $invalidPoams += "$($entry.poamId) (Likelihood too low: $likelihood, Expected at least: $relevanceOfThreat or $impact)"
        }
    }
}

# Set concernPoams to "NONE" if empty
if ($concernPoams.Count -eq 0) { $concernPoams = @("NONE") }

# Output results
if ($Test128Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: All POA&Ms follow Risk Analysis 'Likelihood' guidance." -InformationVariable Test128Info
    $PassCount++
} elseif ($Test128Result -eq "CONCERN") {
    Write-Host -ForegroundColor Yellow "CONCERN: Some POA&Ms have missing 'Likelihood' values. Manual verification required. $($concernPoams -join ', ')"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: Some POA&Ms have incorrect 'Likelihood' values: $($invalidPoams -join ', ') The Following POA&Ms have missing 'Likelihood' values. Manual verification required for: $($concernPoams -join ', ')" -InformationVariable Test128Info
    $FailCount++
}



<#
Test 129: Does 'Impact' match System 'Impact Level' for all POA&M records with 'Ongoing' and 'Risk Accepted' status?
#>
Write-Host ""
Write-Host -ForegroundColor Cyan "Test 129: Does 'Impact' match System 'Impact Level' for all POA&M records with 'Ongoing' and 'Risk Accepted' status?"
Write-Host ""

# Initialize test result
$Test129Result = "PASS"

# Retrieve system impact level
$systemImpact = $null

foreach ($entry in $filteredSystemData) {
    if ($entry.impact -and $entry.impact -ne "-" -and $entry.impact -ne "") {
        $systemImpact = $entry.impact
        break
    }
}

# If no system impact level is found, raise concern
if (-not $systemImpact) {
    Write-Host -ForegroundColor Yellow "CONCERN: System Impact Level is missing or undefined."
    $Test129Result = "CONCERN"
}

# Initialize tracking variables
$invalidPoams = @()  # Store POA&Ms that fail the test

# Iterate through POA&M records
foreach ($entry in $filteredPoamData) {
    # Only check POA&Ms that are "Ongoing" or "Risk Accepted"
    if ($entry.status -in @("Ongoing", "Risk Accepted")) {
        # Skip POA&Ms missing an impact value
        if (-not $entry.impact -or $entry.impact -eq "" -or $entry.impact -eq "-") {
            continue
        }

        # Validate that POA&M impact matches system impact level
        if ($entry.impact -ne $systemImpact) {
            $Test129Result = "FAIL"
            $invalidPoams += "$($entry.poamId) (System Impact: $systemImpact, Found: $($entry.impact))"
        }
    }
}

# Output results
if ($Test129Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: All 'Ongoing' and 'Risk Accepted' POA&Ms have an impact level matching the system's impact level." -InformationVariable Test129Info
    $PassCount++
} elseif ($Test129Result -eq "CONCERN") {
    Write-Host -ForegroundColor Yellow "CONCERN: System Impact Level is missing or undefined. Unable to verify POA&M impact consistency." -InformationVariable Test129Info
} else {
    Write-Host -ForegroundColor Red "FAIL: Some 'Ongoing' and 'Risk Accepted' POA&Ms have an impact level that does not match the system's impact level. Affected POA&Ms: $($invalidPoams -join ', ')" -InformationVariable Test129Info
    $FailCount++
}

<#

Test 130: 'Residual Risk' values match recommended values

#>
Write-Host ""
Write-Host -ForegroundColor Cyan "Test 130: Residual Risk values must align with NIST 800-30 Rev. 1, Table I-2."
Write-Host ""

# Initialize test result
$Test130Result = "PASS"

# Define the corrected NIST Residual Risk mapping (Likelihood x Impact)
$nistRiskMatrix = @{
    "Very High" = @{ "Very Low" = "Very Low"; "Low" = "Low"; "Moderate" = "Moderate"; "High" = "High"; "Very High" = "Very High" }
    "High"      = @{ "Very Low" = "Very Low"; "Low" = "Low"; "Moderate" = "Moderate"; "High" = "Moderate"; "Very High" = "High" }
    "Moderate"  = @{ "Very Low" = "Very Low"; "Low" = "Low"; "Moderate" = "Moderate"; "High" = "Moderate"; "Very High" = "Moderate" }
    "Low"       = @{ "Very Low" = "Very Low"; "Low" = "Very Low"; "Moderate" = "Low"; "High" = "Low"; "Very High" = "Moderate" }
    "Very Low"  = @{ "Very Low" = "Very Low"; "Low" = "Very Low"; "Moderate" = "Very Low"; "High" = "Low"; "Very High" = "Low" }
}

# Initialize tracking variables
$invalidPoams = @()  # Store POA&Ms that fail the test

# Iterate through POA&M records
foreach ($entry in $filteredPoamData) {
    $likelihood = $entry.likelihood
    $impact = $entry.impact
    $residualRisk = $entry.residualRiskLevel
    $justification = $entry.impactDescription  # Assumed to store justification

    # Skip if likelihood or impact is missing (incomplete data)
    if (-not $likelihood -or -not $impact -or -not $residualRisk) {
        continue
    }

    # Check if there's a NIST-recommended residual risk for the given Likelihood & Impact
    if ($nistRiskMatrix.ContainsKey($likelihood) -and $nistRiskMatrix[$likelihood].ContainsKey($impact)) {
        $expectedRisk = $nistRiskMatrix[$likelihood][$impact]

        # If residual risk deviates from expected, check for justification
        if ($residualRisk -ne $expectedRisk) {
            if (-not $justification -or $justification -eq "") {
                $Test130Result = "FAIL"
                $invalidPoams += "$($entry.poamId) (Expected: $expectedRisk, Found: $residualRisk)"
            }
        }
    }
}

# Output results
if ($Test130Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: All POA&Ms have correct residual risk levels based on NIST 800-30 Rev. 1." -InformationVariable Test130Info
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: Some POA&Ms have residual risk levels that deviate from NIST standards without justification. Affected POA&Ms: $($invalidPoams -join ', ')" -InformationVariable Test130Info
    $FailCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 131: POA&M Risk levels are at or below the high water marks of the Risk Assessment Module. This check is not against the SAR"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: The eMASS API does not have data for this test." -InformationVariable Test131Info
$Test131Result = "CONCERN"
$ConcernCount++

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 132: POA&M records with 'Status' entries of Ongoing list key events/steps required to close or mitigate the findings as milestones with Scheduled Completion Dates that are realistic and relevant"
Write-Host ""

# Initialize test result
$Test132Result = "PASS"

# Get the current Unix timestamp
$currentUnixTimestamp = [int](Get-Date -UFormat %s)
$oneYearInSeconds = 365 * 24 * 60 * 60  # 1 year in seconds
$ccsdLimitInSeconds = 180 * 24 * 60 * 60  # 180 days in seconds

# Initialize tracking variables
$invalidPoams = @()  # Store POA&Ms that fail the test

# Iterate through POA&M records
foreach ($entry in $filteredPoamData) {
    # Skip inherited POA&Ms
    if ($entry.isInherited -eq $true) {
        continue
    }

    # Process only 'Ongoing' POA&Ms
    if ($entry.status -eq "Ongoing") {
        $milestones = $entry.milestones
        $uniqueDates = @{}  # Hash table to track milestone dates

        $hasValidSteps = $false
        $finalMilestoneIdentified = $false
        $allDatesSame = $true
        $finalCompletionDate = $null

        # Iterate through milestones (if any exist)
        if ($milestones -and $milestones.Count -gt 0) {
            foreach ($milestone in $milestones) {
                $date = $milestone.scheduledCompletionDate
                $desc = $milestone.description

                # Track unique milestone dates
                if ($date -ne $null) {
                    if (-not $uniqueDates.ContainsKey($date)) {
                        $uniqueDates[$date] = 1
                    } else {
                        $uniqueDates[$date]++
                    }

                    # Check if at least one milestone has "Good words" what show explanation, we can add more. This isnt a great way to do this but... yeah what else could I do given my small toolset with powershell
                    if ($desc -match "test|implement|review|schedule|CCB|deployment|mitigation|patch|upgrade|monthly|weekly|biweekly|develop|patching|replace") {
                        $hasValidSteps = $true
                    }

                    # Track final milestone date
                    if ($finalCompletionDate -eq $null -or $date -gt $finalCompletionDate) {
                        $finalCompletionDate = $date
                    }
                }
            }

            # Check if all milestone dates are the same (bad practice)
            if ($uniqueDates.Count -gt 1) {
                $allDatesSame = $false
            }

            # If a contractual delivery milestone is present, ensure it’s marked as final
            if ($milestones[-1].description -match "contractual|final milestone") {
                $finalMilestoneIdentified = $true
            }
        }

        # Validate completion dates
        $creationDate = $entry.createdDate
        if ($finalCompletionDate -ne $null) {
            $timeSinceCreation = $finalCompletionDate - $creationDate

            # Check if completion is within 1 year
            if ($timeSinceCreation -gt $oneYearInSeconds) {
                $Test132Result = "FAIL"
                $invalidPoams += "$($entry.poamId) (Over 1 year)"
            }

            # Check CCSD limit if applicable
            if ($entry.ccsdExpirationDate -ne $null) {
                $ccsdDeadline = $entry.ccsdExpirationDate + $ccsdLimitInSeconds
                if ($finalCompletionDate -gt $ccsdDeadline) {
                    $Test132Result = "FAIL"
                    $invalidPoams += "$($entry.poamId) (CCSD Exceeded)"
                }
            }
        }

        # Final evaluation
        if ($allDatesSame -or -not $hasValidSteps -or -not $finalMilestoneIdentified) {
            $Test132Result = "CONCERN"
            $invalidPoams += "$($entry.poamId) (Bad Milestones)"
        }
    }
}

# Output results
if ($Test132Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: All 'Ongoing' POA&Ms have realistic milestones and valid completion dates." -InformationVariable Test132Info
    $PassCount++
} elseif ($Test132Result -eq "FAIL") {
    Write-Host -ForegroundColor Red "FAIL: Some 'Ongoing' POA&Ms have unrealistic completion dates. Affected POA&Ms: $($invalidPoams -join ', ')" -InformationVariable Test132Info
    $FailCount++
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: Some 'Ongoing' POA&Ms have unrealistic milestones or completion dates. Affected POA&Ms: $($invalidPoams -join ', ')" -InformationVariable Test132Info
    $ConcernCount++
}



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 133: Ongoing POA&Ms with past milestone completion dates must have new milestones and explanations."
Write-Host ""

# Initialize test result
$Test133Result = "PASS"

# Get the current Unix timestamp
$currentUnixTimestamp = [int](Get-Date -UFormat %s)

# Initialize tracking variables
$invalidPoams = @()  # Store POA&Ms that fail the test

# Iterate through POA&M records
foreach ($entry in $filteredPoamData) {
    # Check if POA&M status is "Ongoing"
    if ($entry.status -eq "Ongoing") {
        $hasPastMilestone = $false
        $hasFutureMilestone = $false
        $hasExplanation = $false

        # Check if the POA&M has milestones
        if ($entry.milestones -and $entry.milestones.Count -gt 0) {
            foreach ($milestone in $entry.milestones) {
                # Identify past milestones
                if ($milestone.scheduledCompletionDate -ne $null -and $milestone.scheduledCompletionDate -lt $currentUnixTimestamp) {
                    $hasPastMilestone = $true
                }
                # Identify future milestones
                if ($milestone.scheduledCompletionDate -ne $null -and $milestone.scheduledCompletionDate -gt $currentUnixTimestamp) {
                    $hasFutureMilestone = $true
                }
            }
        }

        # Check if explanation exists in the comments? 
        if ($entry.comments -and $entry.comments -ne "") {
            $hasExplanation = $true
        }

        # Validate: If there's a past milestone, a future milestone and an explanation must exist
        if ($hasPastMilestone -and (-not $hasFutureMilestone -or -not $hasExplanation)) {
            $Test133Result = "FAIL"
            $invalidPoams += $entry.poamId  # Store failing POAM ID
        }
    }
}

# Output results
if ($Test133Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: All 'Ongoing' POA&Ms with missed milestones have future milestones and explanations." -InformationVariable Test133Info
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: Some 'Ongoing' POA&Ms with past milestones lack future milestones or explanations. Affected POA&Ms: $($invalidPoams -join ', ')" -InformationVariable Test133Info
    $FailCount++
}


<#
Test 134: Ensure ALL expired Poams have a pending extension
#>
Write-Host ""
Write-Host -ForegroundColor Cyan "Test 134: Are all expired POA&Ms pending an extension?"
Write-Host ""

# Initialize test result
$Test134Result = "PASS"

# Get the current Unix timestamp
$currentUnixTimestamp = [int](Get-Date -UFormat %s)
# Initialize variable
$expiredPoams = @()
$expiredPoamsnoExtension = @()

# Identify expired POA&Ms
foreach ($entry in $filteredPoamData) {
    if ($entry.scheduledCompletionDate -ne $null -and $entry.scheduledCompletionDate -lt $currentUnixTimestamp) {
        $expiredPoams += $entry
    }
}

# Check if all expired POA&Ms have a pending extension
foreach ($entry in $expiredPoams) {
    if ($entry.pendingExtensionDate -eq $null) {
        $expiredPoamsnoExtension += $entry.displayPoamId
        $Test134Result = "FAIL"
        break
    }
}

# Output results
if ($Test134Result -eq "PASS") {
    Write-Host -ForegroundColor Green "PASS: All expired POA&Ms have a pending extension." -InformationVariable Test134Info
    $PassCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: Some expired POA&Ms do not have a pending extension: "$expiredPoamsnoExtension -InformationVariable Test134Info
    $FailCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 135: 'Source Identifying Vulnerability' information provided in POA&M records with 'Status' entries of Ongoing and Risk Accepted"
Write-Host ""

$failedId = $null

# Initialize the test result
$Test135Result = "PASS"
#Get entries


foreach ($entry in $filteredPoamData) {
    # Check if status is "Risk Accepted" or "Ongoing"
    if ($entry.status -eq "Risk Accepted" -or $entry.status -eq "Ongoing") {
        # Check if sourceIdentifyingVulnerability is null. If so fail.
        if (-not $entry.sourceIdentifyingVulnerability -or $entry.sourceIdentifyingVulnerability -eq "-" -or $entry.sourceIdentifyingVulnerability -eq "") {
        #if null, we fail
            $Test135Result = "FAIL"
            $failedId = $entry.displayPoamId
            break
        }
    }
}

# Final test result
if ($Test135Result -eq "FAIL") {
    
    # Convert Unix timestamp to human-readable format (MM/dd/yyyy hh:mm:ss tt)
    Write-Host "FAIL: No Source Identifying Vulnerability for POAM ID: $failedId" -ForegroundColor Red -InformationVariable Test135Info
    #I know its redundant. I did this to maintain style/maintainability.
    $Test135Result = "FAIL"
    $FailCount++
} else {
    Write-Host "PASS: All poams with a status of Risk Accepted or Ongoing have Source Identifying Vulnerability." -ForegroundColor Green -InformationVariable Test135Info
    $Test135Result = "PASS"
    $PassCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 136: POA&M items requesting 'Risk Acceptance' have valid justification in 'Recommendations' field"
Write-Host ""

$failedId = $null

# Initialize the test result
$Test136Result = "PASS"
#Get entries


foreach ($entry in $filteredPoamData) {
    # Check if recommendations contain "Risk Accepted" or "Accept Risk"
    if ($entry.status -eq "Risk Accepted") {
        # Split recommendations into words and count. The if statment here handles NULLs so we dont split an empty reccomendaitons
        if ($entry.recommendations -ne $null -and $entry.recommendations -ne "") {
            $wordCount = ($entry.recommendations -split "\s+").Count
        } else {
            $wordCount = 0
        }

        # If recommendations where they wanna accept risk have fewer than 6 words, fail. You cant justify accepting risk in less than 6 words
        if ($wordCount -lt 6) {
            $Test136Result = "FAIL"
            $failedId += $entry.poamId
            break

        }
    }
}

# Final test result
if ($Test136Result -eq "FAIL") {
    
    Write-Host "FAIL: Risk acceptance suggested for POAM without solid justificaiton for POAM ID: $failedId" -ForegroundColor Red -InformationVariable Test136Info
    #I know its redundant. I did this to maintain style/maintainability.
    $Test136Result = "FAIL"
    $FailCount++
} else {
    Write-Host "PASS: All reccomendations of risk acceptance are well justified." -ForegroundColor Green -InformationVariable Test136Info
    $Test136Result = "PASS"
    $PassCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 137: POA&M records with a 'Status' entry of Completed have evidence to validate vulnerability was closed "
Write-Host ""

$failedId = $null

# Initialize the test result
$Test137Result = "PASS"
#Get entries to test
foreach ($entry in $filteredPoamData) {
    if (-not $entry.status -or $entry.status -eq "-" -or $entry.status -eq "") {
        #if null, we can skip over it
        continue
    } elseif ($entry.status -eq "Completed") {
        #IF status is completed, we must see if artifacts section exists with SOMETHING in it. if empty fail
        if ($entry.artifacts -or $entry.artifacts -eq "-" -or $entry.artifacts -eq "") {
            #Fail if no artifacts and status is completed
            $Test137Result = "FAIL"
            $failedId += $entry.displayPoamId
            break

        } else {
            continue
        }
    }
}

# Final test result
if ($Test137Result -eq "FAIL") {
    
    # Convert Unix timestamp to human-readable format (MM/dd/yyyy hh:mm:ss tt)
    Write-Host "FAIL: Completed POAM without evidence for POAM ID: $failedId" -ForegroundColor Red -InformationVariable Test137Info
    #I know its redundant. I did this to maintain style/maintainability.
    $Test137Result = "FAIL"
    $FailCount++
} else {
    Write-Host "Concern: No entries have completed status without evidence, manual review required" -ForegroundColor Yellow -InformationVariable Test137Info
    $Test137Result = "CONCERN"
    $ConcernCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 138: False Positives/False Negatives listed in CM-6.5"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: The eMASS API does not have data for this test." -InformationVariable Test138Info
$Test138Result = "CONCERN"
$ConcernCount++



Write-Host ""
Write-Host -ForegroundColor Cyan "Test 139: Are STIG checks present that identify no affected assets or checks with no open finding POA&M items? If so, are those POA&Ms marked 'Completed'?"
Write-Host ""

# Initialize test result
$Test139Result = "PASS"

# Initialize tracking variables
$stigPoams = @()           # Store STIG-related POA&Ms
$completedPoams = @()      # Store STIG POA&Ms correctly marked as "Completed"
$concernPoams = @()        # Store STIG POA&Ms that should be completed but aren't
$failPoams = @()           # Store STIG POA&Ms that outright fail

# Iterate through POA&M records
foreach ($entry in $filteredPoamData) {
    # Identify STIG-related POA&Ms
    if ($entry.sourceIdentifyingVulnerability -match "STIG") {
        $stigPoams += $entry.poamId

        # Check if POA&M has NO affected assets
        $noAffectedAssets = (-not $entry.resources -or $entry.resources -eq "" -or $entry.resources -match "No Resources Affected")

        # If POA&M has no affected assets, it should be marked 'Completed'
        if ($noAffectedAssets) {
            if ($entry.status -eq "Completed") {
                $completedPoams += $entry.poamId
            } else {
                $concernPoams += $entry.poamId
            }
        }
    }
}

# Determine test results
if ($stigPoams.Count -eq 0) {
    # No STIG-related POA&Ms found
    Write-Host -ForegroundColor Yellow "CONCERN: No STIG-related POA&Ms found for review. Manual verification required." -InformationVariable Test139Info
    $ConcernCount++
} elseif ($concernPoams.Count -gt 0) {
    # Some POA&Ms should be completed but aren't
    Write-Host -ForegroundColor Yellow "CONCERN: Some STIG-related POA&Ms have no affected assets but are not marked 'Completed'. Manual review required. Affected POA&Ms: $($concernPoams -join ', ')" -InformationVariable Test139Info
    $ConcernCount++
} else {
    # If all STIG POA&Ms follow the rule, mark test as successful
    Write-Host -ForegroundColor Green "PASS: All STIG-related POA&Ms with no affected assets/findings are correctly marked 'Completed'." -InformationVariable Test139Info
    $PassCount++
}


Write-Host ""
Write-Host -ForegroundColor Cyan "Test 141: No new 'Very High' or 'High' Residual Risk has been identified since last authorization."
Write-Host ""

$failedId = $null

# Initialize the test result
$Test141Result = "PASS"

    foreach ($entry in $filteredPoamData) {
            # Check for missing severity
            if (-not $entry.mitigations -or $entry.mitigations -eq "-" -or $entry.mitigations -eq "") {
                $failedId += $entry.displayPoamId
                $Test141Result = "CONCERN"
                break
            } elseif ($entry.severity -match "(?i)\b(high|very high)\b") {
                # If severity is high or very high and was put there after, fail
                $failedId += $entry.displayPoamId
                $Test141Result = "FAIL"
                break
            }
        }

 
    if ($Test141Result -eq "CONCERN") {
        Write-Host "CONCERN: Missing authorization date or severity: "$failedId -ForegroundColor Yellow -InformationVariable Test141Info
        $ConcernCount++
    } elseif ($Test141Result -eq "FAIL") {
        Write-Host "FAIL: The following POAMS have Very High or High Risk Level which is not authorized: "$failedId -ForegroundColor red -InformationVariable Test141Info
        $FailCount++
    } elseif ($Test141Result -eq "PASS") {
        Write-Host "PASS: All POAMS are in an allowed risk level." -ForegroundColor Green -InformationVariable Test141Info
        $PassCount++
    } 
        
    


Write-Host ""
Write-host -ForegroundColor Cyan "Test 142: Ensure each System has a Signed Appointment Letter"
Write-Host ""

# Define the artifact names to search for
$artifactSearchTerms = @("appointment")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms

#Used for testing
#Write-Host "$filteredArtifacts"

# Mark the Test as Concern If results exist, else fail
if ($filteredArtifacts) {
    #Additional Logic to check if Signed.
    if ($filteredArtifacts) {
        foreach ($artifact in $filteredArtifacts) {
            $signedDate = $artifact."Signed Date" 

            if ($null -ne $signedDate) {
                # Convert Unix timestamp to human-readable format (MM/dd/yyyy hh:mm:ss tt)
                $humanSignedDate = [datetime]::UnixEpoch.AddSeconds($signedDate).ToLocalTime().ToString("MM/dd/yyyy hh:mm:ss tt")

                Write-Host "Test 142: PASS - System Has Signed Appointment letter signed on $humanSignedDate." -ForegroundColor Green -InformationVariable Test142Info
                $PassCount++
                $Pass = $true
                break
            }
        }
    }
    #If files found, but no "signed date. THis could also be considered fail. Advice needed."
    Write-Host "CONCERN: Appointment Letters Found, but cannot be verified signed. Please download and look at the files. "  -ForegroundColor Yellow -InformationVariable Test142Info
    $Test142Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: No Appointment Letters Found. "  -InformationVariable Test142Info
    $Test142Result = "FAIL"
    $FailCount++
}

Write-Host ""
Write-host -ForegroundColor Cyan "Test 143: CONOPs"
Write-Host ""

# Define the artifact names to search for
$artifactSearchTerms = @("CONOP")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms

# Mark the test as a CONCERN/PASS if results exist
if ($filteredArtifacts) {
    Write-Host -ForegroundColor Yellow "CONCERN: CONOP Found, but cannot be verified signed. Please download and look at the files: "$filteredArtifacts  -InformationVariable Test143Info
    $Test143Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: No CONOP Found. "  -InformationVariable Test143Info
    $Test143Result = "FAIL"
    $FailCount++
}




<#
Test 144: Ensure Each system has a "PPS List"
#>
Write-Host ""
Write-host -ForegroundColor Cyan "Test 144: Ensure each System has a PPS List"
Write-Host ""

# Define the artifact names to search for
$artifactSearchTerms = @("PPS")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms

# Mark the test as a CONCERN/PASS if results exist
if ($filteredArtifacts) {
    Write-Host -ForegroundColor Yellow "CONCERN: PPS List Found, but cannot be verified signed. Please download and look at the files. "  -InformationVariable Test144Info
    $Test144Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: No PPS List Found. "  -InformationVariable Test144Info
    $Test144Result = "FAIL"
    $FailCount++
}


<#
Test 145: Ensure Each system has Applicable SOPs signed by current appointed authority and reviewed within the last 365 days"
#>
Write-Host ""
Write-host -ForegroundColor Cyan "Test 145: Ensure each System has Applicable SOPs signed by current appointed authority and reviewed within the last 365 days"
Write-Host ""

# Define the artifact names to search for
$artifactSearchTerms = @("SOP","Standard Operating Procedure")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms

# Check to see if results exist. Further Logic needed to check in UNIX timestamp from submission in last year, then further logic to MAP SOPs to controls
#Perhaps use control name in the filename against maybe control in the securty controls we find from API for the system. This is a simplified BASIC BASIC logic for now.
if ($filteredArtifacts) {
    Write-Host "CONCERN: SOPs found but cannot be mapped and verified signed Please download and look at the files. "  -InformationVariable Test145Info -ForegroundColor Yellow 
    $Test145Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: No SOPs Found. "  -InformationVariable Test145Info 
    $Test145Result = "FAIL"
    $FailCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 146: Are applicable MOUs, MOAs or SLAs between Mission Owners, customer responsibility matrix (CRM), Cloud Service Provider and Cybersecurity Service Provider attached?"
Write-Host ""

# Define the artifact names to search for
$artifactSearchTerms = @("MOU","MOA","SLA","CRM","Cloud Service Provider","Cybersecurity Service Provider")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms

# Check to see if results exist. Further Logic needed to check in UNIX timestamp from submission in last year, then further logic to MAP SOPs to controls
#Perhaps use control name in the filename against maybe control in the securty controls we find from API for the system. This is a simplified BASIC BASIC logic for now.
if ($filteredArtifacts) {
    Write-Host "CONCERN: Relevant Documents Found: "$filteredArtifacts  -InformationVariable Test146Info -ForegroundColor Yellow 
    $Test146Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Red "FAIL: No relevant documents found."  -InformationVariable Test146Info 
    $Test146Result = "FAIL"
    $FailCount++
}

<#
Test 147: Ensure Applicable Systems have PKI Waiver"
#>

Write-Host ""
Write-host -ForegroundColor Cyan "Test 147: Check if Systems have PKI Waivers"
Write-Host ""


# Define the artifact names to search for
$artifactSearchTerms = @("PKI Waiver")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms
#Used For Testing
#Write-Host "$filteredArtifacts"

# Check to see if results exist. Ensure PKI waiver is there. THis needs to be nested to ensure the system is APPLICABLE for this test.
# Else we can skip this check WIP
if ($filteredArtifacts) {
    Write-Host -ForegroundColor Yellow "CONCERN: PKI Waiver Found. "  -InformationVariable Test147Info
    $Test147Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: No PKI Waiver Found. "  -InformationVariable Test147Info
    $Test147Result = "CONCERN"
    $ConcernCount++
}

<#
Test 148: Check If Systems have HBSS Waiver"
#>

Write-Host ""
Write-host -ForegroundColor Cyan "Test 148: Check if Systems have HBSS waivers submitted for them"
Write-Host ""

# Define the artifact names to search for
$artifactSearchTerms = @("HBSS Waiver", "Host Based Security System")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms

# Check to see if results exist. Ensure HBSS waiver is there. THis needs to be nested to ensure the system is APPLICABLE
# for this test and Who is required to have one. Need to see the STIG for HBSS compliance and see if thats listed in API as part of sec plan && who has one. If not have one, better have waiver. More logic needed
# If you are HBSS compliant, we can skip this check WIP
if ($filteredArtifacts) {
    Write-Host -ForegroundColor Yellow "CONCERN: HBSS Waiver Found. "  -InformationVariable Test148Info
    $Test148Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: No HBSS Waiver Found. "  -InformationVariable Test148Info
    $Test148Result = "CONCERN"
    $ConcernCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 149: Check if Systems have PIA - Less than 3 years old"
Write-Host ""


#calculate dates needed for documents being older than 3 years. 
$ThreeYearsAgoDate = (Get-Date).AddDays(-1095)
$ThreeYearsAgoEpoch = (New-TimeSpan -Start (Get-Date "01/01/1970") -End ($ThreeYearsAgoDate)).TotalSeconds

$PIADocument = $null

foreach ($Artifacts2 in $ArtifactDetailsData) {
    if (($artifacts2.name -like "PIA" -or $artifacts2.filename -like "PIA") -or ($artifacts2.name -like "Privacy Impact Assessment" -or $artifacts2.filename -like "Privacy Impact Assessment") -and $artifacts2."Signed Date" -ge $ThreeYearsAgoEpoch) {
        $PIADocument += $Artifacts2.filename
    } else {
        
    }
}

if ($null -eq $PIADocument) {
    Write-Host -ForegroundColor Red "FAIL: No PIA documents have been found signed within the last three years" -InformationVariable Test149Info
    $Test149Result = "FAIL"
    $FailCount++
} else {
    Write-Host -ForegroundColor Green "PASS: The PIA document has been found: "$PIADocument -InformationVariable Test149Info
    $Test149Result = "PASS"
    $PassCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 150:  Ensure Each system have SCA-V/SCA-O SAR"
Write-Host ""

# Define the artifact names to search for
$artifactSearchTerms = @("SCA-V", "SCA-O", "SAR")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms

# Check to see if results exist. 
if ($filteredArtifacts) {
    Write-Host "PASS: SCA-V, SCA-O Found for System $systemId "  -InformationVariable Test150Info -ForegroundColor Green
    $Test150Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: No SCA-V, SCA-O Found. "  -InformationVariable Test150Info
    $Test150Result = "CONCERN"
    $ConcernCount++
}

Write-Host ""
Write-host -ForegroundColor Cyan "Test 151:  Ensure Each system has SCA-V/SCA-O Reccomendation Memo"
Write-Host ""

# Define the artifact names to search for
$artifactSearchTerms = @("SCA-O Recommendation Memo", "Recommendation Memo", "SCA-V Recommendation Memo")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms

# Check to see if results exist. 
if ($filteredArtifacts) {
    Write-Host "PASS: SCA-O SCA-A Reccomendation Memo Found "  -InformationVariable Test151Info -ForegroundColor Green
    $Test151Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: No SCA-V Reccomendation Memo or SCA-O Reccomendation Memo Found. "  -InformationVariable Test151Info
    $Test151Result = "CONCERN"
    $FailCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 152: Ensure Each system have Nessus/ACAS  Assessment Scan Results"
Write-Host ""

# Define the artifact names to search for
$artifactSearchTerms = @("Nessus", "ACAS", "Assessment Scan Results")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms

# Check to see if results exist. 
if ($filteredArtifacts) {
    Write-Host "PASS: Nessus/ACAS  Assessment Scan Results Found "  -InformationVariable Test152Info -ForegroundColor Green
    $Test152Result = "PASS"
    #$PassCount++
} else {
    Write-Host -ForegroundColor Yellow "Fail: No Nessus/ACAS  Assessment Scan Results Found. "  -InformationVariable Test152Info
    $Test152Result = "FAIL"
    #$FailCount++
}

Write-Host ""
Write-host -ForegroundColor Cyan "Test 153: Ensure Each system have Nessus/ACAS  Assessment Scan Results in CSV or .Nessus Format from last 30 days"
Write-Host ""

# Define the artifact names to search for
$artifactSearchTerms = @("Nessus", "ACAS", "Assessment Scan Results")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms

# Get the current Unix epoch time
$currentUnixTime = [int][double]::Parse((Get-Date -UFormat %s))

# Get Unix time for 30 days ago
$thirtyDaysAgo = $currentUnixTime - (30 * 86400)  # 86400 seconds in a day

$Pass = $false

# Run the loop only if filteredArtifacts is not null or empty
if ($filteredArtifacts) {
    foreach ($artifact in $filteredArtifacts) {
        $lastModified = $artifact."Last Modified"
        $filename = $artifact."Filename"

        # Ensure values are not null
        if ($null -ne $lastModified -and $null -ne $filename) {
            
            # Check if Last Modified is within the last 30 days
            $isRecent = $lastModified -ge $thirtyDaysAgo

            # Check if Filename ends in .nessus or .csv (case-insensitive)
            $isValidFile = $filename -match "\.nessus$|\.csv$"

            # Convert Unix timestamp to human-readable format for display
            $humanLastModified = [datetime]::UnixEpoch.AddSeconds($lastModified).ToLocalTime().ToString("MM/dd/yyyy hh:mm:ss tt")

            if ($isRecent -and $isValidFile) {
                Write-Host "Test 153: PASS - '$filename' was modified on $humanLastModified. Scan submitted in proper format within past 20 days" -ForegroundColor Green -InformationVariable Test153Info
                $PassCount++
                $Pass = $true
                break  # Stop looping on first pass
            }
        }
    }
}

# Fail if no valid artifact was found
if (-not $Pass) {
    Write-Host "Test 153: FAIL - No valid Scan results found within last 30 days with correct file extensions." -ForegroundColor Red -InformationVariable Test153Info
    $Test153Result = "FAIL"
    $FailCount++
}

Write-Host ""
Write-host -ForegroundColor Cyan "Test 154:  Ensure Each system has All Self-Assessment .ckls are completed per requirements"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: The eMASS API does not have data for this test." -InformationVariable Test154Info
$Test154Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-host -ForegroundColor Cyan "Test 155:  Check if a Fielding Manual, Deployment Guide or similar artifact available that identifies the receiving unit responsibilities? *may only apply to SIS/CRN systems that are responsible as the CSSP Provider*"
Write-Host ""

# Define the artifact names to search for
$artifactSearchTerms = @("Fielding Guide", "Fielding Manual", "Deployment Guide", "Deployment Manual")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms

# Check to see if results exist. 
if ($filteredArtifacts) {
    Write-Host "CONCERN: Fielding Manual/Deployment guide present"  -InformationVariable Test155Info -ForegroundColor Yellow
    $Test155Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: NO Fielding Manual/Deployment guide found"  -InformationVariable Test155Info
    $Test155Result = "CONCERN"
    $ConcernCount++
}
#End Artifacts SECTION


Write-Host ""
Write-host -ForegroundColor Cyan "Test 156:  Does system have a previous Control Assessor recommendation or had an independent validation?"
Write-Host ""


# Define the artifact names to search for
$artifactSearchTerms = @("Control Assessor", "Independent Validation", "SCA-V")

# Call the function with pre-filtered JSON
$filteredArtifacts = Get-ArtifactInfo -apiData $filteredJArtifactsJsonObject -artifactNames $artifactSearchTerms

# Check to see if results exist. 
if ($filteredArtifacts) {
    Write-Host "PASS: Control Assessor or Independent Validation Found: "$filteredArtifacts  -InformationVariable Test156Info -ForegroundColor Green
    $Test156Result = "PASS"
    $PassCount++
} else {
    Write-Host -ForegroundColor Yellow "CONCERN: No Relevant Documents Found"  -InformationVariable Test156Info
    $Test156Result = "CONCERN"
    $ConcernCount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 157:  Terms/conditions of previous authorization decision addressed?"
Write-Host ""

$TermsConditionsApprovalWorkflow = $WorkflowHistoryDataSorted | Where-Object {$_.'workflow' -like "*Conditions*"} | Sort-Object -Property "lastEditedDate" -Descending | Select-Object -First 1

if ($null -eq $TermsConditionsApprovalWorkflow) {
    Write-Host "FAIL: Terms and Conditions Approval Workflow was not found."  -InformationVariable Test157Info -ForegroundColor Red
    $Test157Result = "FAIL"
    $FailCount++
} else {
    Write-Host "PASS: Terms and Conditions Approval Workflow was found: "$TermsConditionsApprovalWorkflow.packagename  -InformationVariable Test157Info -ForegroundColor Green
    $Test157Result = "PASS"
    $PassCount++
}

Write-Host ""
Write-host -ForegroundColor Cyan "Test 158: Receiving inheritance from 'CCP' and inheritance Tier1 CCP and Tier 2 CCP have been removed?"
Write-Host ""

$inheritancedata = Get-Content (join-path $DemoAssets "Associations.json") | ConvertFrom-Json
$inheritancedatasorted = $inheritancedata.data | Where-Object {$_."System ID" -eq $systemID}

$badinheritance = $null

foreach ($association in $inheritancedatasorted) {
    if ($association."Associated System ID" -like "3915" -or $association."Associated System ID" -like "2315") {
        $badinheritance += $association."Associated System ID"
    }
}

if ($null -eq $badinheritance ) {
    Write-Host "FAIL: The system in inheriting from system ID 3915 or 2315: "$badinheritance  -InformationVariable Test158Info -ForegroundColor Red
    $Test158Result = "FAIL"
    $FailCount++
} else {
    Write-Host "PASS: The not allowed inheritances are not present"  -InformationVariable Test158Info -ForegroundColor Green
    $Test158Result = "PASS"
    $PassCount++
}

Write-Host ""
Write-host -ForegroundColor Cyan "Test 159: Are all applicable inheritance relationships established?"
Write-Host ""

$MAINPolicyRecord = $null
$CCPCloudRecord = $null
$CCPRecord = $null

foreach ($association in $inheritancedatasorted) {
    if ($association."Associated System ID" -like "4642") {
        $MAINPolicyRecord += $association."Associated System ID"
    }
}

foreach ($association in $inheritancedatasorted) {
    if ($association."Associated System ID" -like "5050") {
        $CCPCloudRecord += $association."Associated System ID"
    }
}

foreach ($association in $inheritancedatasorted) {
    if ($association."Associated System ID" -like "3915") {
        $CCPRecord += $association."Associated System ID"
    }
}

if ($null -eq $MAINPolicyRecord) {
    Write-Host "FAIL: The system is missing the Policy Record"  -InformationVariable Test159Info -ForegroundColor Red
    $Test159Result = "FAIL"
    $FailCount++
} else {
    if ($Cloud -like "True") {
        if ($null -eq $CCPCloudRecord) {
            Write-Host "FAIL: The Cloud system is missing the CCP Cloud policy record"  -InformationVariable Test159Info -ForegroundColor Red
            $Test159Result = "FAIL"
            $FailCount++
        } else {
            Write-Host "PASS: The Cloud system has the CCP Policy Records"  -InformationVariable Test159Info -ForegroundColor Green
            $Test159Result = "PASS"
            $PassCount++
        }
    } else {
        if ($null -eq $CCPRecord) {
            Write-Host "FAIL: The system is missing the CCP policy record"  -InformationVariable Test159Info -ForegroundColor Red
            $Test159Result = "FAIL"
            $FailCount++
        } else {
            Write-Host "PASS: The system has the CCP Policy Records"  -InformationVariable Test159Info -ForegroundColor Green
            $Test159Result = "PASS"
            $PassCount++
        }
    }
}

Write-Host ""
Write-host -ForegroundColor Cyan "Test 160: Are there Controls/CCIs being inherited from the Enterprise Cloud CCP and additional provider(s)? Hybrid controls are acceptable."
Write-Host ""

if ($Cloud -like "True") {
    if ($null -eq $CCPCloudRecord) {
        Write-Host "FAIL: The Cloud system is missing the CCP Cloud policy record"  -InformationVariable Test160Info -ForegroundColor Red
        $Test160Result = "FAIL"
        $FailCount++
    } else {
        Write-Host "PASS: The Cloud system has the CCP Policy Records"  -InformationVariable Test160Info -ForegroundColor Green
        $Test160Result = "PASS"
        $PassCount++
    }
} else {
    Write-Host "NA: The system is not a cloud system"  -InformationVariable Test160Info -ForegroundColor Gray
    $Test160Result = "N/A"
    $NACount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 161: Are there any CCI's inherited that have an associated STIG? *Exception for Hybrid Controls*"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: The eMASS API does not have data for this test." -InformationVariable Test161Info
$Test161Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-host -ForegroundColor Cyan "Test 162: Are there any critical controls that are being inherited by system from an inheritance relationship that are Non-Compliant? 'Do the Red Critical POAMs have an effective Mitigation?"
Write-Host ""

$noncompliantCriticalInherited = $null

foreach ($criticalcontrol2 in $criticalcontrolinfodata) {
    if ($criticalcontrol2.isInherited -like "True" -and $criticalcontrol2.complianceStatus -like "NC") {
        $noncompliantCriticalInherited += $criticalcontrol2.acronym
    }
}

if ($null -eq $noncompliantCriticalInherited) {
    Write-Host "PASS: There are no inherited critical controls that are non compliant"  -InformationVariable Test162Info -ForegroundColor Green
    $Test162Result = "PASS"
    $PassCount++
} else {
    Write-Host "FAIL: There are no inherited critical controls that are non compliant: "$noncompliantCriticalInherited  -InformationVariable Test162Info -ForegroundColor Red
    $Test162Result = "FAIL"
    $FailCount++
}

Write-Host ""
Write-host -ForegroundColor Cyan "Test 163: Cybersecurity Service Provider (CSSP) Inheritance established and/or not aligned with cloud service model and data impact level? *if applicable*"
Write-Host ""

$CSSPCloud = $null
$CSSPNotCloud = $null

foreach ($association in $inheritancedatasorted) {
    if ($association."Associated System ID" -like "5206" -or $association."Associated System ID" -like "2555" -or $association."Associated System ID" -like "2409") {
        $CSSPCloud += $association."Associated System ID"
    }
}

foreach ($association in $inheritancedatasorted) {
    if ($association."Associated System ID" -like "367") {
        $CSSPNotCloud += $association."Associated System ID"
    }
}

if ($cloud -like "True") {
    if ($null -eq $CSSPCloud) {
        Write-Host "FAIL: The Cloud system is missing the CSSP Inheritance"  -InformationVariable Test163Info -ForegroundColor Red
        $Test163Result = "FAIL"
        $FailCount++
    } else {
        Write-Host "PASS: The Cloud system has the CSSP Inheritance"  -InformationVariable Test163Info -ForegroundColor Green
        $Test159Result = "PASS"
        $PassCount++
    }
} else {
    if ($null -eq $CSSPNotCloud) {
        Write-Host "FAIL: The system is missing the CSSP Inheritance"  -InformationVariable Test163Info -ForegroundColor Red
        $Test163Result = "FAIL"
        $FailCount++
    } else {
        Write-Host "PASS: The system has the CSSP Inheritance"  -InformationVariable Test163Info -ForegroundColor Green
        $Test163Result = "PASS"
        $PassCount++
    }
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 164: Does the Production cloud system have an established inheritance relationship with C5ISR and does the CSO Impact Level (example IL4, IL5)match the system details? *will be added to T&C for IATT & non-prod cloud systems*"
Write-Host ""

$C5ISRInheritance = $null

foreach ($association in $inheritancedatasorted) {
    if ($association."Associated System ID" -like "4894" -or $association."Associated System ID" -like "5035" -or $association."Associated System ID" -like "3694" -or $association."Associated System ID" -like "3696" -or $association."Associated System ID" -like "3692" -or $association."Associated System ID" -like "3695" -or $association."Associated System ID" -like "3697") {
        $C5ISRInheritance += $association."Associated System ID"
    }
}

if ($cloud -like "True") {
    if ($null -eq $C5ISRInheritance) {
        Write-Host "FAIL: The system is missing the C5ISR Inheritance"  -InformationVariable Test164Info -ForegroundColor Red
        $Test164Result = "FAIL"
        $FailCount++
    } else {
        Write-Host "PASS: The system has the C5ISR Inheritance"  -InformationVariable Test164Info -ForegroundColor Green
        $Test164Result = "PASS"
        $PassCount++
    }

} else {
    Write-Host "NA: The system is not a cloud system"  -InformationVariable Test164Info -ForegroundColor Gray
    $Test164Result = "N/A"
    $NACount++
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 165: Manual inheritance established for any control inherited but not captured under a policy record"
Write-Host ""

Write-Host -ForegroundColor Yellow "CONCERN: The eMASS API does not have data for this test." -InformationVariable Test165Info
$Test165Result = "CONCERN"
$ConcernCount++


Write-Host ""
Write-host -ForegroundColor Cyan "Test 168: Documented 'Associations' listed as needed *should include any Dependencies listed in data*"
Write-Host ""

$dataAssociationMatch = $null
$dataAssociationNOTMatch = $null

#Pull from data
$dataParentSystems = $dataReport[0]."Parent System Name"
$dataChildSystems = $dataReport[0]."Child System Name"

$dataAssociations = $dataParentSystems + $dataChildSystems


foreach ($dataItem in $dataAssociations) {
    foreach ($association in $inheritancedatasorted) {
        if ($dataItem -like "*$($association."Associated System Acronym")*") {
            $dataAssociationMatch += $association."Associated System Acronym"
        }
    }
    if ($dataAssociationMatch -match $dataItem) {
            
    } else {
        $dataAssociationNOTMatch += $dataItem
    }
}


if ($null -eq $dataParentSystems -and $null -eq $dataChildSystems) {
    Write-Host "NA: The system does not have dependencies in data"  -InformationVariable Test166Info -ForegroundColor Gray
    $Test166Result = "N/A"
    $NACount++
} elseif ($dataParentSystems -eq "" -and $dataChildSystems -eq "") {
    Write-Host "NA: The system does not have dependencies in data"  -InformationVariable Test166Info -ForegroundColor Gray
    $Test166Result = "N/A"
    $NACount++

} else {

    if ($null -eq $dataAssociationNOTMatch -and $null -ne $dataAssociationMatch) {
        Write-Host "PASS: The dependencies in data match eMASS"  -InformationVariable Test166Info -ForegroundColor Green
        $Test166Result = "PASS"
        $PassCount++
    } elseif ($null -ne $dataAssociationNOTMatch) {
        Write-Host "FAIL: The system has data Associations without being in eMASS: "$dataAssociationNOTMatch  -InformationVariable Test166Info -ForegroundColor Red
        $Test166Result = "FAIL"
        $FailCount++
    } else {
        Write-Host -ForegroundColor Yellow "CONCERN: The data and eMASS associations matching could not be determined." -InformationVariable Test166Info
        $Test166Result = "CONCERN"
        $ConcernCount++
    }
}


Write-Host ""
Write-host -ForegroundColor Cyan "Test 167: Documented 'External Systems' listed as needed"
Write-Host ""

$externalsystems = 0

foreach ($association in $inheritancedatasorted) {
    if ($association."External System" -like "Yes") {
        $externalsystems++
    }
}

if ($externalsystems -eq 0) {
    Write-Host -ForegroundColor Yellow "CONCERN: There are zero external systems documented" -InformationVariable Test167Info
    $Test167Result = "CONCERN"
    $ConcernCount++
} else {
    Write-Host "PASS: Number of external systems documented: "$externalsystems  -InformationVariable Test167Info -ForegroundColor Green
    $Test167Result = "PASS"
    $PassCount++
}

Start-Sleep -Seconds 2

#FUNCTION

function Get-MatchingUser {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [object[]] $apiData,                 # already filtered to this $SystemID by caller
        [Parameter(Mandatory)]
        [string]   $rolePattern              # e.g. "ISO", "Organizational ISSM", "AO", etc.
    )

    # Map each requested role to the text you actually expect to see in the JSON "Role" field.
    # Matching is case-insensitive and substring-based.
    $roleSynonyms = @{
        'ISO'               = @('ISO','ISO/PM','Information System Owner')
        'ISO/PM/ISSO'       = @('ISO','ISO/PM','ISSO','Program Manager','PM','Information System Security Officer')
        'Organizational ISSM' = @('Organizational ISSM','O-ISSM','ISSM')
        'Program ISSM'      = @('Program ISSM','P-ISSM','ISSM')
        'SCA-R'             = @('SCA-R','Security Control Assessor (Risk)')
        'SCA-A'             = @('SCA-A','Security Control Assessor (Assessment)')
        'SCA-V'             = @('SCA-V','Security Control Assessor (Validation)')
        'AO'                = @('AO','Authorizing Official')
        'AODR'              = @('AODR')
        'Network AO'        = @('Network AO','NAO')
        'Network AODR'      = @('Network AODR','NAODR')
    }

    $alts = if ($roleSynonyms.ContainsKey($rolePattern)) {
        $roleSynonyms[$rolePattern]
    } else {
        @($rolePattern)  # fall back to the literal pattern
    }

    # Find first row whose Role contains one of the synonyms
    $candidates = foreach ($row in $apiData) {
        $roleVal = if ($row.PSObject.Properties.Name -contains 'Role') { [string]$row.Role } else { '' }
        if (-not [string]::IsNullOrWhiteSpace($roleVal)) {
            foreach ($alt in $alts) {
                if ($roleVal -imatch [regex]::Escape($alt)) {
                    # prefer rows with more specific (longer) role strings by tagging a score
                    [pscustomobject]@{
                        Row   = $row
                        Role  = $roleVal
                        Score = $alt.Length
                    }
                    break
                }
            }
        }
    }

    if (-not $candidates -or $candidates.Count -eq 0) {
        return @('FAIL', $null, $null)
    }

    # Pick the best (highest Score, then first)
    $best = $candidates | Sort-Object -Property Score -Descending | Select-Object -First 1 | ForEach-Object { $_.Row }

    # Extract names using the actual keys present in UserDetails.json
    $first = if ($best.PSObject.Properties.Name -contains 'First Name') { [string]$best.'First Name' } else { $null }
    $last  = if ($best.PSObject.Properties.Name -contains 'Last Name')  { [string]$best.'Last Name'  } else { $null }

    return @('PASS', $first, $last)
}




#FUNCTION END

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 168: Correct PAC ISO/PM Present"
Write-Host ""

Start-Sleep -Seconds 2

$UserDetails = Get-Content (Join-Path $DemoAssets "UserDetails.json") | ConvertFrom-Json
$UserDetailsSorted = $UserDetails.data | Where-Object { $_."System ID" -eq $SystemID }

# --- Test 168 ---
$Test168ResultArray = Get-MatchingUser -apiData $UserDetailsSorted -rolePattern "ISO"
if ($null -eq $Test168ResultArray -or ($Test168ResultArray -isnot [System.Array]) -or $Test168ResultArray.Count -lt 1) {
    $Test168Result = "FAIL"
    Write-Host -ForegroundColor Red "FAIL: The ISO/PM is not provided" -InformationVariable Test168Info
    $FailCount++
} else {
    $Test168Result = $Test168ResultArray[0]
    if ($Test168Result -eq "PASS") {
        Write-Host -ForegroundColor Green "PASS: The PAC/ISO is: $($Test168ResultArray[1]) $($Test168ResultArray[2])" -InformationVariable Test168Info
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: The ISO/PM is not provided" -InformationVariable Test168Info
        $FailCount++
    }
}


[Console]::Out.Flush()

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 169: Correct PAC O-ISSM Present"
Write-Host ""

Start-Sleep -Seconds 2

$Test169ResultArray = Get-MatchingUser -apiData $UserDetailsSorted -rolePattern "Organizational ISSM"
if ($null -eq $Test169ResultArray -or ($Test169ResultArray -isnot [System.Array]) -or $Test169ResultArray.Count -lt 1) {
    $Test169Result = "FAIL"
    Write-Host -ForegroundColor Red "FAIL: The O-ISSM is not provided" -InformationVariable Test169Info
    $FailCount++
} else {
    $Test169Result = $Test169ResultArray[0]
    if ($Test169Result -eq "PASS") {
        Write-Host -ForegroundColor Green "PASS: The system owner is: $($Test169ResultArray[1]) $($Test169ResultArray[2])" -InformationVariable Test169Info
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: The O-ISSM is not provided" -InformationVariable Test169Info
        $FailCount++
    }
}

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 170: Correct PAC P-ISSM Present"
Write-Host ""

Start-Sleep -Seconds 2

$Test170ResultArray = Get-MatchingUser -apiData $UserDetailsSorted -rolePattern "Program ISSM"
if ($null -eq $Test170ResultArray -or ($Test170ResultArray -isnot [System.Array]) -or $Test170ResultArray.Count -lt 1) {
    $Test170Result = "FAIL"
    Write-Host -ForegroundColor Red "FAIL: The P-ISSM is not provided" -InformationVariable Test170Info
    $FailCount++
} else {
    $Test170Result = $Test170ResultArray[0]
    if ($Test170Result -eq "PASS") {
        Write-Host -ForegroundColor Green "PASS: The P-ISSM is: $($Test170ResultArray[1]) $($Test170ResultArray[2])" -InformationVariable Test170Info
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: The P-ISSM is not provided" -InformationVariable Test170Info
        $FailCount++
    }
}

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 171: Correct PAC Representative Present"
Write-Host ""

Start-Sleep -Seconds 2

$Test171ResultArray = Get-MatchingUser -apiData $UserDetailsSorted -rolePattern "SCA-R"
if ($null -eq $Test171ResultArray -or ($Test171ResultArray -isnot [System.Array]) -or $Test171ResultArray.Count -lt 1) {
    $Test171Result = "FAIL"
    Write-Host -ForegroundColor Red "FAIL: The Representative is not provided" -InformationVariable Test171Info
    $FailCount++
} else {
    $Test171Result = $Test171ResultArray[0]
    if ($Test171Result -eq "PASS") {
        Write-Host -ForegroundColor Green "PASS: The Representative is: $($Test171ResultArray[1]) $($Test171ResultArray[2])" -InformationVariable Test171Info
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: The Representative is not provided" -InformationVariable Test171Info
        $FailCount++
    }
}

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 172: Correct PAC Assessor Present"
Write-Host ""

Start-Sleep -Seconds 2

$Test172ResultArray = Get-MatchingUser -apiData $UserDetailsSorted -rolePattern "SCA-A"
if ($null -eq $Test172ResultArray -or ($Test172ResultArray -isnot [System.Array]) -or $Test172ResultArray.Count -lt 1) {
    $Test172Result = "FAIL"
    Write-Host -ForegroundColor Red "FAIL: The Assessor is not provided" -InformationVariable Test172Info
    $FailCount++
} else {
    $Test172Result = $Test172ResultArray[0]
    if ($Test172Result -eq "PASS") {
        Write-Host -ForegroundColor Green "PASS: The Assessor is: $($Test172ResultArray[1]) $($Test172ResultArray[2])" -InformationVariable Test172Info
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: The Assessor is not provided" -InformationVariable Test172Info
        $FailCount++
    }
}

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 173: Correct PAC AO Present"
Write-Host ""

Start-Sleep -Seconds 2

$Test173ResultArray = Get-MatchingUser -apiData $UserDetailsSorted -rolePattern "AO"
if ($null -eq $Test173ResultArray -or ($Test173ResultArray -isnot [System.Array]) -or $Test173ResultArray.Count -lt 1) {
    $Test173Result = "FAIL"
    Write-Host -ForegroundColor Red "FAIL: The AO is not provided" -InformationVariable Test173Info
    $FailCount++
} else {
    $Test173Result = $Test173ResultArray[0]
    if ($Test173Result -eq "PASS") {
        Write-Host -ForegroundColor Green "PASS: The AO is: $($Test173ResultArray[1]) $($Test173ResultArray[2])" -InformationVariable Test173Info
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: The AO is not provided" -InformationVariable Test173Info
        $FailCount++
    }
}

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 174: Correct PAC AO Rep Present"
Write-Host ""

Start-Sleep -Seconds 2

$Test174ResultArray = Get-MatchingUser -apiData $UserDetailsSorted -rolePattern "AODR"
if ($null -eq $Test174ResultArray -or ($Test174ResultArray -isnot [System.Array]) -or $Test174ResultArray.Count -lt 1) {
    $Test174Result = "FAIL"
    Write-Host -ForegroundColor Red "FAIL: The AO Rep is not provided" -InformationVariable Test174Info
    $FailCount++
} else {
    $Test174Result = $Test174ResultArray[0]
    if ($Test174Result -eq "PASS") {
        Write-Host -ForegroundColor Green "PASS: The AO Rep is: $($Test174ResultArray[1]) $($Test174ResultArray[2])" -InformationVariable Test174Info
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: The AO Rep is not provided" -InformationVariable Test174Info
        $FailCount++
    }
}

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 175: Correct PAC Network AO Present"
Write-Host ""

Start-Sleep -Seconds 2

$Test175ResultArray = Get-MatchingUser -apiData $UserDetailsSorted -rolePattern "Network AO"
if ($null -eq $Test175ResultArray -or ($Test175ResultArray -isnot [System.Array]) -or $Test175ResultArray.Count -lt 1) {
    $Test175Result = "FAIL"
    Write-Host -ForegroundColor Red "FAIL: The Network AO is not provided" -InformationVariable Test175Info
    $FailCount++
} else {
    $Test175Result = $Test175ResultArray[0]
    if ($Test175Result -eq "PASS") {
        Write-Host -ForegroundColor Green "PASS: The Network AO is: $($Test175ResultArray[1]) $($Test175ResultArray[2])" -InformationVariable Test175Info
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: The Network AO is not provided" -InformationVariable Test175Info
        $FailCount++
    }
}

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 176: Correct PAC Network AO Rep Present"
Write-Host ""

Start-Sleep -Seconds 2

$Test176ResultArray = Get-MatchingUser -apiData $UserDetailsSorted -rolePattern "Network AODR"
if ($null -eq $Test176ResultArray -or ($Test176ResultArray -isnot [System.Array]) -or $Test176ResultArray.Count -lt 1) {
    $Test176Result = "FAIL"
    Write-Host -ForegroundColor Red "FAIL: The Network AO Rep is not provided" -InformationVariable Test176Info
    $FailCount++
} else {
    $Test176Result = $Test176ResultArray[0]
    if ($Test176Result -eq "PASS") {
        Write-Host -ForegroundColor Green "PASS: The Network AO Rep is: $($Test176ResultArray[1]) $($Test176ResultArray[2])" -InformationVariable Test176Info
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: The Network AO Rep is not provided" -InformationVariable Test176Info
        $FailCount++
    }
}

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 177: Correct PAC ISO/PM/ISSO Present"
Write-Host ""

Start-Sleep -Seconds 2

$Test177ResultArray = Get-MatchingUser -apiData $UserDetailsSorted -rolePattern "ISO/PM/ISSO"
if ($null -eq $Test177ResultArray -or ($Test177ResultArray -isnot [System.Array]) -or $Test177ResultArray.Count -lt 1) {
    $Test177Result = "FAIL"
    Write-Host -ForegroundColor Red "FAIL: The ISO/PM/ISSO is not provided" -InformationVariable Test177Info
    $FailCount++
} else {
    $Test177Result = $Test177ResultArray[0]
    if ($Test177Result -eq "PASS") {
        Write-Host -ForegroundColor Green "PASS: The ISO/PM/ISSO is: $($Test177ResultArray[1]) $($Test177ResultArray[2])" -InformationVariable Test177Info
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: The ISO/PM/ISSO is not provided" -InformationVariable Test177Info
        $FailCount++
    }
}

Write-Host ""
Write-Host -ForegroundColor Cyan "Test 178: Correct PAC Validator Present"
Write-Host ""

Start-Sleep -Seconds 2

$Test178ResultArray = Get-MatchingUser -apiData $UserDetailsSorted -rolePattern "SCA-V"
if ($null -eq $Test178ResultArray -or ($Test178ResultArray -isnot [System.Array]) -or $Test178ResultArray.Count -lt 1) {
    $Test178Result = "FAIL"
    Write-Host -ForegroundColor Red "FAIL: The Validator is not provided" -InformationVariable Test178Info
    $FailCount++
} else {
    $Test178Result = $Test178ResultArray[0]
    if ($Test178Result -eq "PASS") {
        Write-Host -ForegroundColor Green "PASS: The SCA-V is: $($Test178ResultArray[1]) $($Test178ResultArray[2])" -InformationVariable Test178Info
        $PassCount++
    } else {
        Write-Host -ForegroundColor Red "FAIL: The SCA-V is not provided" -InformationVariable Test178Info
        $FailCount++
    }
}

#Managment SECTION END

Start-Sleep -Seconds 1

#Run and display test result totals.
$TestTotal = $PassCount + $FailCount + $ConcernCount + $NACount


Write-Host ""
Write-Host ""
Write-Host -ForegroundColor Cyan    "Test Result Counts"
Write-Host ""
Write-Host -ForegroundColor Cyan    "Total Number of Tests:   "$TestTotal
Write-Host -ForegroundColor Green   "Number Passed:           "$PassCount
Write-Host -ForegroundColor Red     "Number Failed:           "$FailCount
Write-Host -ForegroundColor Yellow  "Number Concern:          "$ConcernCount
Write-Host -ForegroundColor Gray    "Number N/A:              "$NACount
Write-Host ""

Start-Sleep -Seconds 1

    $cellvalues = @{

        # Row 5 (Test 1)
        "E5" = "$Test1Result"
        "G5" = "$Test1Info"
        
        # Row 6 (Test 2)
        "E6" = "$Test2Result"
        "G6" = "$Test2Info"
        
        # Row 7 (Test 3)
        "E7" = "$Test3Result"
        "G7" = "$Test3Info"
        
        # Row 8 (Test 4)
        "E8" = "$Test4Result"
        "G8" = "$Test4Info"
        
        # Row 9 (Test 5)
        "E9" = "$Test8Result"
        "G9" = "$Test8Info"
        
        # Row 10 (Test 6)
        "E10" = "$Test9Result"
        "G10" = "$Test9Info"
        
        # Row 11 (Test 7)
        "E11" = "$Test10Result"
        "G11" = "$Test10Info"
        
        # Row 12 (Test 8)
        "E12" = "$Test11Result"
        "G12" = "$Test11Info"
        
        # Row 13 (Test 9)
        "E13" = "$Test13Result"
        "G13" = "$Test13Info"
        
        # Row 14 (Test 10)
        "E14" = "$Test14Result"
        "G14" = "$Test14Info"
        
        # Row 15 (Test 11)
        "E15" = "$Test15Result"
        "G15" = "$Test15Info"
        
        # Row 16 (Test 12)
        "E16" = "$Test16Result"
        "G16" = "$Test16Info"
        
        # Row 17 (Test 13)
        "E17" = "$Test17Result"
        "G17" = "$Test17Info"
        
        # Row 18 (Test 14)
        "E18" = "$Test18Result"
        "G18" = "$Test18Info"
        
        # Row 19 (Test 15)
        "E19" = "$Test19Result"
        "G19" = "$Test19Info"
        
        # Row 20 (Test 16)
        "E20" = "$Test20Result"
        "G20" = "$Test20Info"
        
        # Row 21 (Test 17)
        "E21" = "$Test21Result"
        "G21" = "$Test21Info"
        
        # Row 22 (Test 18)
        "E22" = "$Test22Result"
        "G22" = "$Test22Info"
        
        # Row 23 (Test 19)
        "E23" = "$Test23Result"
        "G23" = "$Test23Info"
        
        # Row 24 (Test 20)
        "E24" = "$Test24Result"
        "G24" = "$Test24Info"
        
        # Row 25 (Test 21)
        "E25" = "$Test25Result"
        "G25" = "$Test25Info"
        
        # Row 26 (Test 22)
        "E26" = "$Test26Result"
        "G26" = "$Test26Info"
        
        # Row 27 (Test 23)
        "E27" = "$Test27Result"
        "G27" = "$Test27Info"
        
        # Row 28 (Test 24)
        "E28" = "$Test28Result"
        "G28" = "$Test28Info"
        
        # Row 29 (Test 25)
        "E29" = "$Test29Result"
        "G29" = "$Test29Info"
        
        # Row 30 (Test 26)
        "E30" = "$Test30Result"
        "G30" = "$Test30Info"
        
        # Row 31 (Test 27)
        "E31" = "$Test31Result"
        "G31" = "$Test31Info"
        
        # Row 32 (Test 28)
        "E32" = "$Test32Result"
        "G32" = "$Test32Info"
        
        # Row 33 (Test 29)
        "E33" = "$Test33Result"
        "G33" = "$Test33Info"
        
        # Row 34 (Test 30)
        "E34" = "$Test35Result"
        "G34" = "$Test35Info"

        # Row 35 Skipped 
        
        # Row 36 (Test 32)
        "E36" = "$Test36Result"
        "G36" = "$Test36Info"
        
        # Row 37 (Test 33)
        "E37" = "$Test37Result"
        "G37" = "$Test37Info"
        
        # Row 38 (Test 34)
        "E38" = "$Test38Result"
        "G38" = "$Test38Info"
        
        # Row 39 (Test 39)
        "E39" = "$Test39Result"
        "G39" = "$Test39Info"

        # Row 40 Skipped
        
        # Row 41 (Test 36)
        "E41" = "$Test40Result"
        "G41" = "$Test40Info"
        
        # Row 42 (Test 37)
        "E42" = "$Test41Result"
        "G42" = "$Test41Info"
        
        # Row 43 (Test 38)
        "E43" = "$Test42Result"
        "G43" = "$Test42Info"
        
        # Row 44 (Test 39)
        "E44" = "$Test43Result"
        "G44" = "$Test43Info"
        
        # Row 45 (Test 40)
        "E45" = "$Test44Result"
        "G45" = "$Test44Info"
        
        # Row 46 Skip

        # Row 47 (Test 41)
        "E47" = "$Test47Result"
        "G47" = "$Test47Info"
        
        # Row 48 (Test 42)
        "E48" = "$Test48Result"
        "G48" = "$Test48Info"
        
        # Row 49 (Test 43)
        "E49" = "$Test49Result"
        "G49" = "$Test49Info"
        
        # Row 50 (Test 51)
        "E50" = "$Test51Result"
        "G50" = "$Test51Info"
        
        # Row 51 (Test 45)
        "E51" = "$Test52Result"
        "G51" = "$Test52Info"
        
        # Row 52 (Test 46)
        "E52" = "$Test53Result"
        "G52" = "$Test53Info"
        
        # Row 53 (Test 47)
        "E53" = "$Test54Result"
        "G53" = "$Test54Info"

        # Row 54 Skipped
        
        # Row 55 (Test 48)
        "E55" = "$Test55Result"
        "G55" = "$Test55Info"
        
        # Row 56 (Test 49)
        "E56" = "$Test56Result"
        "G56" = "$Test56Info"
        
        # Row 57 (Test 50)
        "E57" = "$Test57Result"
        "G57" = "$Test57Info"
        
        # Row 58 (Test 51)
        "E58" = "$Test58Result"
        "G58" = "$Test58Info"
        
        # Row 59 (Test 52)
        "E59" = "$Test59Result"
        "G59" = "$Test59Info"
        
        # Row 60 is skipped

        # Row 61 (Test 53)
        "E61" = "$Test60Result"
        "G61" = "$Test60Info"
        
        # Row 62 is skipped
        
        # Row 63 (Test 54)
        "E63" = "$Test61Result"
        "G63" = "$Test61Info"
        
        # Row 64 Skipped
        
        # Row 65 (Test 56)
        "E65" = "$Test62Result"
        "G65" = "$Test62Info"
        
        # Row 66 skipped

        # Row 67 is skipped
        "E67" = "$Test63Result"
        "G67" = "$Test63Info"

        # Row 68 (Test 59)
        "E68" = "$Test64Result"
        "G68" = "$Test64Info"
        
        # Row 69 is skipped
        "E69" = "$Test65Result"
        "G69" = "$Test65Info"
        
        # Row 70 (Test 60)
        "E70" = "$Test66Result"
        "G70" = "$Test66Info"
        
        # Row 71 is skipped

        # Row 72 (Test 61)
        "E72" = "$Test67Result"
        "G72" = "$Test67Info"
        
        # Row 74 (Test 62)
        "E73" = "$Test68Result"
        "G73" = "$Test68Info"
        
        # Row 74 Skipped
        
        # Row 75 (Test 63)
        "E75" = "$Test69Result"
        "G75" = "$Test69Info"
        
        # Row 76 (Test 64)
        "E76" = "$Test70Result"
        "G76" = "$Test70Info"
        
        # Row 77 Skipped
      
        # Row 78 is skipped
        "E78" = "$Test71Result"
        "G78" = "$Test71Info"

        # Row 79 (Test 66)
        "E79" = "$Test34Result"
        "G79" = "$Test34Info"
        
        # Row 80 (Test 67)
        "E80" = "$Test72Result"
        "G80" = "$Test72Info"
        
        # Row 81 (Test 73)
        "E81" = "$Test73Result"
        "G81" = "$Test73Info"

        # Row 82 (Test 68)
        "E82" = "$Test74Result"
        "G82" = "$Test74Info"
        
        # Row 83 (Test 69)
        "E83" = "$Test75Result"
        "G83" = "$Test75Info"
        
        # Row 84 
        "E84" = "$Test76Result"
        "G84" = "$Test76Info"

        # Row 85 (Test 70)
        "E85" = "$Test78Result"
        "G85" = "$Test78Info"
        
        # Row 86 (Test 71)
        "E86" = "$Test79Result"
        "G86" = "$Test79Info"
        
        # Row 87 (Test 72)
        "E87" = "$Test80Result"
        "G87" = "$Test80Info"
        
        # Row 88 (Test 73)
        "E88" = "$Test81Result"
        "G88" = "$Test81Info"
        
        # Row 89 Skipped
        
        # Row 90 (Test 75)
        "E90" = "$Test82Result"
        "G90" = "$Test82Info"
        
        # Row 91 (Test 76)
        "E91" = "$Test83Result"
        "G91" = "$Test83Info"
        
        # Row 92 (Test 77)
        "E92" = "$Test85Result"
        "G92" = "$Test85Info"
        
        # Row 93 (Test 78)
        "E93" = "$Test84Result"
        "G93" = "$Test84Info"
        
        # Row 94 (Test 79)
        "E94" = "$Test91Result"
        "G94" = "$Test91Info"
        
        # Row 95 (Test 80)
        "E95" = "$Test92Result"
        "G95" = "$Test92Info"
        
        # Row 96 (Test 93)
        "E96" = "$Test93Result"
        "G96" = "$Test93Info"

        # Row 97 Skipped
        
        # Row 98 (Test 82)
        "E98" = "$Test86Result"
        "G98" = "$Test86Info"
        
        # Row 99 (Test 83)
        "E99" = "$Test87Result"
        "G99" = "$Test87Info"
        
        # Row 100 (Test 84)
        "E100" = "$Test88Result"
        "G100" = "$Test88Info"
        
        # Row 101 (Test 85)
        "E101" = "$Test89Result"
        "G101" = "$Test89Info"
        
        # Row 102 (Test 86)
        "E102" = "$Test90Result"
        "G102" = "$Test90Info"
        
        # Row 103 (Test 87)
        "E103" = "$Test94Result"
        "G103" = "$Test94Info"
        
        # Row 104 is skipped
        "E104" = "$Test95Result"
        "G104" = "$Test95Info"

        # Row 105 (Test 88)
        "E105" = "$Test96Result"
        "G105" = "$Test96Info"
        
        # Row 106 Skipped
        
        # Row 107 (Test 90)
        "E107" = "$Test97Result"
        "G107" = "$Test97Info"
        
        # Row 108 (Test 91)
        "E108" = "$Test98Result"
        "G108" = "$Test98Info"
        
        # Row 109 Skipped
        
        # Row 110 (Test 93)
        "E110" = "$Test99Result"
        "G110" = "$Test99Info"
        
        # Row 111 (Test 94)
        "E111" = "$Test100Result"
        "G111" = "$Test100Info"
        
        # Row 112 Skipped
        
        # Row 113 (Test 101)
        "E113" = "$Test101Result"
        "G113" = "$Test101Info"

        # Row 114 (Test 96)
        "E114" = "$Test102Result"
        "G114" = "$Test102Info"
        
        # Row 115 (Test 97)
        "E115" = "$Test103Result"
        "G115" = "$Test103Info"
        
        # Row 116 (Test 104)
        "E116" = "$Test104Result"
        "G116" = "$Test104Info"

        # Row 117 Skipped
        
        # Row 118 (Test 99)
        "E118" = "$Test106Result"
        "G118" = "$Test106Info"
        
        # Row 119 is skipped
        "E119" = "$Test108Result"
        "G119" = "$Test108Info"

        # Row 120 Skipped
        
        # Row 121 (Test 101)
        "E121" = "$Test109Result"
        "G121" = "$Test109Info"
        
        # Row 122 Skipped
        
        # Row 123 (Test 103)
        "E123" = "$Test110Result"
        "G123" = "$Test110Info"
        
        # Row 124 Skipped
    
        # Row 125 is skipped
        "E125" = "$Test111Result"
        "G125" = "$Test111Info"

        # Row 126 (Test 105)
        "E126" = "$Test112Result"
        "G126" = "$Test112Info"
        
        # Row 127 (Test 106)
        "E127" = "$Test113Result"
        "G127" = "$Test113Info"
        
        # Row 128 is skipped
        "E128" = "$Test114Result"
        "G128" = "$Test114Info"

        # Row 129 (Test 107)
        "E129" = "$Test115Result"
        "G129" = "$Test115Info"
        
        # Row 130 is skipped

        # Row 131 (Test 108)
        "E131" = "$Test116Result"
        "G131" = "$Test116Info"
        
        # Row 132 is skipped
        "E132" = "$Test117Result"
        "G132" = "$Test117Info"

        # Row 133 (Test 109)
        "E133" = "$Test118Result"
        "G133" = "$Test118Info"
        
        # Row 134 (Test 110)
        "E134" = "$Test119Result"
        "G134" = "$Test119Info"
        
        # Row 135 Skipped
        
        # Row 136 (Test 112)
        "E136" = "$Test120Result"
        "G136" = "$Test120Info"
        
        # Row 137 (Test 113)
        "E137" = "$Test121Result"
        "G137" = "$Test121Info"
        
        # Row 138 is skipped
        "E138" = "$Test122Result"
        "G138" = "$Test122Info"

        # Row 139 (Test 114)
        "E139" = "$Test123Result"
        "G139" = "$Test123Info"
        
        # Row 140 (Test 115)
        "E140" = "$Test124Result"
        "G140" = "$Test124Info"
        
        # Row 141 (Test 116)
        "E141" = "$Test125Result"
        "G141" = "$Test125Info"
        
        # Row 142 (Test 117)
        "E142" = "$Test126Result"
        "G142" = "$Test126Info"
        
        # Row 143 
        "E143" = "$Test127Result"
        "G143" = "$Test127Info"

        # Row 144 (Test 118)
        "E144" = "$Test128Result"
        "G144" = "$Test128Info"
        
        # Row 145 (Test 119)
        "E145" = "$Test129Result"
        "G145" = "$Test129Info"
        
        # Row 146 (Test 120)
        "E146" = "$Test130Result"
        "G146" = "$Test130Info"
        
        # Row 147 (Test 121)
        "E147" = "$Test131Result"
        "G147" = "$Test131Info"
        
        # Row 148 (Test 122)
        "E148" = "$Test132Result"
        "G148" = "$Test132Info"
    
        # Row 149 (Test 123)
        "E149" = "$Test133Result"
        "G149" = "$Test133Info"
        
        # Row 150 (Test 124)
        "E150" = "$Test134Result"
        "G150" = "$Test134Info"
        
        # Row 151 (Test 125)
        "E151" = "$Test135Result"
        "G151" = "$Test135Info"
        
        # Row 152 (Test 126)
        "E152" = "$Test136Result"
        "G152" = "$Test137Info"
        
        # Row 153 (Test 127)
        "E153" = "$Test137Result"
        "G153" = "$Test137Info"
        
        # Row 154 (Test 128)
        "E154" = "$Test138Result"
        "G154" = "$Test138Info"
        
        # Row 155 (Test 129)
        "E155" = "$Test139Result"
        "G155" = "$Test139Info"
        
        # Row 156 (Test 130)
        "E156" = "$Test141Result"
        "G156" = "$Test141Info"
        
        # Row 157 skipped
        
        # Row 158 (Test 132)
        "E158" = "$Test142Result"
        "G158" = "$Test142Info"
        
        # Row 159 (Test 133)
        "E159" = "$Test143Result"
        "G159" = "$Test143Info"
        
        # Row 160 (Test 134)
        "E160" = "$Test144Result"
        "G160" = "$Test144Info"
        
        # Row 161 (Test 135)
        "E161" = "$Test145Result"
        "G161" = "$Test145Info"
        
        # Row 162 (Test 136)
        "E162" = "$Test146Result"
        "G162" = "$Test146Info"
        
        # Row 163 (Test 137)
        "E163" = "$Test147Result"
        "G163" = "$Test147Info"
        
        # Row 164 (Test 138)
        "E164" = "$Test148Result"
        "G164" = "$Test148Info"
        
        # Row 165 (Test 139)
        "E165" = "$Test149Result"
        "G165" = "$Test149Info"
        
        # Row 166 is skipped
        "E166" = "$Test150Result"
        "G166" = "$Test150Info"

        # Row 167 (Test 140)
        "E167" = "$Test151Result"
        "G167" = "$Test151Info"
        
        # Row 168 (Test 141)
        "E168" = "$Test152Result"
        "G168" = "$Test152Info"
        
        # Row 169 (Test 142)
        "E169" = "$Test153Result"
        "G169" = "$Test153Info"
        
        # Row 170 (Test 143)
        "E170" = "$Test154Result"
        "G170" = "$Test154Info"
        
        # Row 171 (Test 144)
        "E171" = "$Test155Result"
        "G171" = "$Test155Info"
        
        # Row 172 Skipped
        
        # Row 173 (Test 146)
        "E173" = "$Test156Result"
        "G173" = "$Test156Info"
        
        # Row 174 (Test 147)
        "E174" = "$Test157Result"
        "G174" = "$Test157Info"
        
        # Row 175 Skipped
        
        # Row 176 (Test 149)
        "E176" = "$Test158Result"
        "G176" = "$Test158Info"
        
        # Row 177 (Test 150)
        "E177" = "$Test159Result"
        "G177" = "$Test159Info"
        
        # Row 178 (Test 151)
        "E178" = "$Test160Result"
        "G178" = "$Test160Info"
        
        # Row 179 (Test 152)
        "E179" = "$Test161Result"
        "G179" = "$Test161Info"
        
        # Row 180 (Test 153)
        "E180" = "$Test162Result"
        "G180" = "$Test162Info"
        
        # Row 181 is skipped
        "E181" = "$Test163Result"
        "G181" = "$Test163Info"

        # Row 182 (Test 154)
        "E182" = "$Test164Result"
        "G182" = "$Test164Info"
        
        # Row 183 (Test 155)
        "E183" = "$Test165Result"
        "G183" = "$Test165Info"
        
        # Row 184 is skipped

        # Row 185 (Test 156)
        "E185" = "$Test166Result"
        "G185" = "$Test166Info"
        
        # Row 186 (Test 157)
        "E186" = "$Test167Result"
        "G186" = "$Test167Info"
        
        # Row 187 Skipped
        
        # Row 188 (Test 159)
        "E188" = "$Test168Result"
        "G188" = "$Test168Info"
        
        # Row 189 (Test 160)
        "E189" = "$Test169Result"
        "G189" = "$Test169Info"
        
        # Row 190 (Test 161)
        "E190" = "$Test170Result"
        "G190" = "$Test170Info"
        
        # Row 191 (Test 162)
        "E191" = "$Test171Result"
        "G191" = "$Test171Info"
        
        # Row 192 (Test 163)
        "E192" = "$Test172Result"
        "G192" = "$Test172Info"
        
        # Row 193 is skipped
        "E193" = "$Test173Result"
        "G193" = "$Test173Info"

        # Row 194 (Test 164)
        "E194" = "$Test174Result"
        "G194" = "$Test174Info"
        
        # Row 195 (Test 165)
        "E195" = "$Test175Result"
        "G195" = "$Test175Info"
        
        # Row 196 is skipped
        "E196" = "$Test176Result"
        "G196" = "$Test176Info"

        # Row 197 Skipped
        
        # Row 198 (Test 167)
        "E198" = "$Test177Result"
        "G198" = "$Test177Info"
        
        # Row 199 (Test 168)
        "E199" = "$Test178Result"
        "G199" = "$Test178Info"
       
        
        }  # End of $cellvalues
        

    Write-Host -ForegroundColor Cyan "Writing Report for System. . . " 

      

    # Convert $cellvalues to JSON
    $cellvalues.GetEnumerator() | ForEach-Object {
        [PSCustomObject]@{ Cell = $_.Key; Value = $_.Value }
    } | ConvertTo-Json -Depth 3 | Out-File $OutputJson -Encoding UTF8

#stop the clock
$EndTime = Get-Date

$ElapsedTime = New-TimeSpan -Start $StartTime -End $EndTime

# Display the elapsed time
Write-Host -ForegroundColor Cyan "Elapsed time: $($ElapsedTime.ToString())"

Write-host -ForegroundColor Cyan "Writing Data for Reporting Page"

Start-Sleep -Seconds 1
[Console]::Out.Flush()



# Auto-generated PowerShell script to build JSON test summary

# Step 1: Declare $testSections
$testSections = @(
  @{
    name = "System";
    tests = @(
      @{ var = "test1"; name = "If Assess Only, System 'Mission Criticality' and CIA values adhere to the Assess Only Approval path documented in section 4, figure 2 of the Assess Only TTP?" },
      @{ var = "test2"; name = "Workflow title has the correct Naming Convention" },
      @{ var = "test3"; name = "eMASS 'System Name' matches APMS 'Item Name'" },
      @{ var = "test4"; name = "eMASS 'Acronym' matches APMS 'Acronym'" },
      @{ var = "test5"; name = "Authorization Termination Date' inline with APMS" },
      @{ var = "test6"; name = "'National Security System' matches APMS and ITS *the Privacy Overlay  should be applied if the NSS processes, stores or transmits PII'*" },
      @{ var = "test7"; name = "National Security System' checklist filled out completely?" },
      @{ var = "test8"; name = "'Financial Management System' matches APMS 'Account System Feeder'" },
      @{ var = "test9"; name = "If 'Public Facing Component / Presence:' is Yes; does the Auth Boundary identify the public facing component/capability, IP & FQDN provided, Whitelisted and Publicly accessible?" },
      @{ var = "test10"; name = "Systems contains CUI, PII and/or PHI and matches APMS" },
      @{ var = "test11"; name = "'System Description' matches APMS 'Description' (no deviations allowed)" },
      @{ var = "test12"; name = "'APMS ID' matches eMASS 'AITR' Number" },
      @{ var = "test13"; name = "System User Categories' Identify roles, responsibilities and categories for system" },
      @{ var = "test14"; name = "Is this a Cloud Computer? 

Does the Cloud Computer' match the Infrastructure section in APMS *confirm correct Cloud Type & Service Model are selected if applicable*

Has the system onboarded with ECMA if hosted in GovCloud [e.g., cARMY, DISA Hosted Cloud]?" },
      @{ var = "test15"; name = "Does the commercial cloud system have a Impact Level of 4 or 5?" },
      @{ var = "test16"; name = "Does the Cloud Service Offering (CSO) have a current DoD PA? *not applicable for cARMY or DISA Hosted Cloud*

Does the CSO have a pending submission for DoD PA?

Does the DoD PA align with the identified impact level (IL)? Check the security control inheritance with the Cloud Service Provider (CSP) / CSO, system details, and Network Topology diagrams.

Does the CSO have a FEDRAMP approval?" },
      @{ var = "test17"; name = "'PPSM Registry Number' Provided *required for SaaS (all impact levels)*" },
      @{ var = "test18"; name = "System Authorization Boundary' has an Executive Summary on the System Details tab, the Artifact is Linked or attached, and has a date less than 1 year old.
*review Cloud checks if applicable*" },
      @{ var = "test19"; name = "Are the HW & SW Baselines populated? ''Hardware / Software / Firmware' has an Executive Summary on the System Details tab, the Artifact is Linked or attached, and has a date less than 1 year old. *template must be used to meet requirement*" },
      @{ var = "test20"; name = "'System Enterprise and Information Security Architecture' has an Executive Summary on the System Details tab, the Artifact is Linked or attached, and has a date less than 1 year old." },
      @{ var = "test21"; name = "'Information Flows / Paths' has an Executive Summary on the System Details tab, the Artifact is Linked or attached, and has a date less than 1 year old.  *Does the CRN IV diagram depict encryption techniques used to protect data?*" },
      @{ var = "test22"; name = "Is there a clear depiction of the Cloud Service Provider (CSP) / CSO within the Network Topology Diagrams?" },
      @{ var = "test23"; name = "Does the Network Topology Diagrams show connection of the CSP to customers via Cloud Access Point (CAP) for sensitive data (CUI as handled at Impact Levels 4/5 or classified information up to SECRET as handled at Level 6)?

NOTE: IL 4/5 - A Boundary CAP (BCAP) is required to connect off-premises non-DoD (commercially or governmentally) owned and operated CSOs to the DISN (or other DoD networks)." },
      @{ var = "test24"; name = "Does the Network Topology Diagrams align with the cloud service model?" },
      @{ var = "test25"; name = "Is there an entry in the DMZ whitelist?

NOTE: If all or a portion of the cloud-based level 4/5 systems/applications are connected through the BCAP and are to be internet accessible; the system’s/application’s URLs/IP addresses must be registered with the DoD DMZ whitelist [can be found on SIPRNet at https://niprdmzwhitelist.csd.disa.smil.mil/home.aspx]." },
      @{ var = "test26"; name = "'Network Connection Rules' provided? If yes, artifact such as ISA provided?" },
      @{ var = "test27"; name = "‘Interconnected Information Systems and Identifiers’ provided? If yes, artifact such as ISA provided?

NOTE: CSD ISA template is available." },
      @{ var = "test28"; name = "Encryption Techniques' provided to protect DAR and DIT [CUI/PII/PH data] *confirm encryption technique(s) are provided if CRN IV system*" },
      @{ var = "test29"; name = "'Cryptographic Key Management Information' (e.g., public key infrastructures, certificate authorities, EKMS, KMI, etc.) *confirm cryptographic key management used if CRN IV system*" },
      @{ var = "test30"; name = "Does system have a registration in the Authorizing Official Repository (AO-R)?" },
      @{ var = "test31"; name = "System Location' is correct" },
      @{ var = "test32"; name = "'Deployment Locations' Provided" },
      @{ var = "test33"; name = "Baseline Location' Provided" },
      @{ var = "test34"; name = "Physical Location(s)' Provided" },
      @{ var = "test35"; name = "Approved SP obtained within one year" },
      @{ var = "test36"; name = "'System Life Cycle / Acquisition Phase' Provided" },
      @{ var = "test37"; name = "'Type Authorization' is Yes" },
      @{ var = "test38"; name = "Highest System Data Classification" },
      @{ var = "test39"; name = "'RMF Activity' identifies current RMF phase" },
      @{ var = "test40"; name = "Security Review field(s) answered" },
      @{ var = "test41"; name = "Contingency Plan field(s) answered" },
      @{ var = "test42"; name = "Incident Response Plan field(s) answered" },
      @{ var = "test43"; name = "Disaster Recover Plan field(s) answered" },
      @{ var = "test44"; name = "Privacy Impact Assessment field(s) answered" },
      @{ var = "test45"; name = "Privacy Act System of Record Notice field answered" },
      @{ var = "test46"; name = "E-Authentication Risk Assessment field(s) answered" },
      @{ var = "test47"; name = "Mission Criticality' matches APMS *If Assess Only, System ‘Mission Criticality’ allows for Assess Only*" },
      @{ var = "test48"; name = "'Governing Mission Area' matches APMS 'System Mission Area'" },
      @{ var = "test49"; name = "'Acquisition Category' matches APMS" },
      @{ var = "test50"; name = "Software Category' matches APMS *Assess Only*" },
      @{ var = "test51"; name = "'System Ownership / Controlled' matches APMS 'System Operation'" },
      @{ var = "test52"; name = "All External Security Services (ESS) Fields Addressed *must be filled out if the system is on the DoDIN or in the Cloud*" },
      @{ var = "test53"; name = "Connection point(s) details provided if applicable [Connectivity/CCSD]

'Is the Connectivity field populated? 

If Connectivity is SIS or CRN in Connectivity/CCSD section in eMASS, is 'System Name' and 'Acronym' correctly identified?" },
      @{ var = "test54"; name = "All ATC/IATC Fields Addressed (only applies if the Org owns the circuit/CCSD)" },
      @{ var = "test55"; name = "‘Applied Information Types’ Matches Information Type Survey (ITS) Evidence Artifact" },
      @{ var = "test56"; name = "'Control Attributes' Matches Information Type Evidence Artifact" },
      @{ var = "test57"; name = "'Impact Level' Identified" },
      @{ var = "test58"; name = "'Information Type Evidence' Artifact Linked" },
      @{ var = "test59"; name = "Are any Overlays applied to the system and have all Overlay questions been answered?" },
      @{ var = "test60"; name = "Overlay/Tailored" },
      @{ var = "test61"; name = "Have 'STIGS/SRGs' been identified for all security relevant Hardware, Software and functions as validated against, HW/SW List and Module, Diagrams, ACAS Scans & Other relevant system information?" },
      @{ var = "test62"; name = "Recommended Added Controls are addressed?

Add Recommended controls should = 0. If not, this will result in a Return for Rework." }
    )
  },
  @{
    name = "Controls";
    tests = @(
      @{ var = "test63"; name = "Does system have any significant changes since last Authorization" },
      @{ var = "test64"; name = "Assessed 'Non Compliant' and 'Not Applicable' controls without an active POA&M Item = 0 and verify that all failed checks have a POA&M" },
      @{ var = "test65"; name = "All 14 ATC Critical Controls are in the system Baseline? 

Unassessed Red Critical & FISMA Controls?

All Red Critical & FISMA controls/APs/CCIs have test results in eMASS that are less than 1 yr old?" },
      @{ var = "test66"; name = "All controls have a status of Official or Validated? Exception with those with traceability through a POA&M" },
      @{ var = "test67"; name = "Not Applicable’ CCI’s have valid justification for status." },
      @{ var = "test68"; name = "SLCM [ConMon] strategy [for all Controls including Red Critical and FISMA controls], correlation and analysis activities, and response actions are documented and associated to CA-7." },
      @{ var = "test69"; name = "Incident Response Plan provided as an artifact for IR-8 and evidence of most recent IR Test provided in IR-3." },
      @{ var = "test70"; name = "For Assess Only packages where there is scannable Hardware and Software is RA-5 in the baseline?" },
      @{ var = "test71"; name = "For Assess Only packages where CSSP inheritance cannot be established and no CSSP artifact is present, have the following controls been addressed (cannot be N/A)? 
AC-2.9, AC-2.18 , SA-5.10, SA-11.4, SA-11.8, SC-5.1, SI-2.2, SI-2.4" },
      @{ var = "test72"; name = "'Compliant' Controls have 'Implemented' or 'Inherited' Implementation Status" },
      @{ var = "test73"; name = "Non-Compliant Controls have 'Planned' or 'Not Implemented' Implementation Status" },
      @{ var = "test74"; name = "'Not Applicable' Controls have 'Not Applicable' or 'Inherited' Implementation Status" },
      @{ var = "test75"; name = "Estimated Completion Date' (ECD) is in the future for Control's with a 'Planned' Implementation Status; ECD is current or is in the past for Controls with an  'Implemented' Implementation Status; ECD is 'blank' for Controls with a 'Not Applicable' Implementation Status." },
      @{ var = "test76"; name = "Common Control Provider identified for inherited controls & correct Security Control Designation listed?" },
      @{ var = "test77"; name = "Implementation Narrative" },
      @{ var = "test78"; name = "Responsible Entities" },
      @{ var = "test79"; name = "Completed Risk Assessment" },
      @{ var = "test80"; name = "ATC Specific controls that are Not Compliant have a Risk Assessment Summary entry" },
      @{ var = "test81"; name = "Non-Compliant' Controls:  Vulnerability Summary, Impact Description, and Recommendations have a response" },
      @{ var = "test82"; name = "Compliant' Controls:  Vulnerability Summary, Impact Description, and Recommendations have been removed" },
      @{ var = "test83"; name = "Not Applicable' Controls: Vulnerability Summary, Impact Description, and Recommendations have been removed" },
      @{ var = "test84"; name = "Risk Attribute for Impact Description matches system categorization C-I-A impact level" },
      @{ var = "test85"; name = "All Risk Attributes are populated IAW Army Risk Analysis and do not deviate from Recommended values without documentation and support for change." },
      @{ var = "test86"; name = "Are any DoD Tier1 CCP, Army Tier2 CCP or Army Sentinel CCP controls showing up passing inheritance through the system?" }
    )
  },
  @{
    name = "Assets";
    tests = @(
      @{ var = "test87"; name = "There are no 'Enter Non-Compliant Test Results for Compliant APs' suggested actions" },
      @{ var = "test88"; name = "Are all errors cleared? (Incorrect Compliance status, failed security checks, POA&M's to close,…)" },
      @{ var = "test89"; name = "There are no 'Conflicted Findings' with technical scan results." },
      @{ var = "test90"; name = "There are no 'Unmapped Findings'" },
      @{ var = "test91"; name = "Does record contain benchmark technical data?" },
      @{ var = "test92"; name = "Does the record contain current STIG/SRG technical data and are all applicable STIGs/SRGs current IAW the DISA Version | Release?" },
      @{ var = "test93"; name = "ACAS scans for 100% of the devices within the last 30 days or IAW any AO approved exceptions as required by TASKORD 20-0020. *ASR/ARF requires informational plugins and plugin 19506*" },
      @{ var = "test94"; name = "Any vulnerability that remains open has an associated POA&M with mitigations sufficient to lower the risk of the vulnerability" },
      @{ var = "test95"; name = "Have Code analysis scans been provided for any system, including Public Facing systems, using Government Developed, GOTS or Open Source Software? *confirm the baseline has been tailored to include the following as applicable*:                      
-SA-11 (1) when source code is available
-SA-11 (8) when source code is not available
-SI-2 when source code dependencies are available" },
      @{ var = "test96"; name = "Is there traceability between the devices in the Resources Module and the devices documented in the system Diagrams, HW/SW Lists and HW/SW Module?" },
      @{ var = "test97"; name = "'Component Type', 'Asset Name', 'IP Address' (if applicable), 'Public Facing', 'Public Facing FQDN', 'Public Facing IP Address' , Public Facing URL(s)' (if applicable), 'Virtual Asset', 'Manufacturer', 'Model Number', 'Serial Number' (if applicable), 'OS/iOS/FW Version', 'Location' provided for each component listed" },
      @{ var = "test98"; name = "All component types listed appear in the 'System Authorization Boundary' Artifact" },
      @{ var = "test99"; name = "All OS/iOS/FW versions listed on the 'System Authorization Boundary' Artifact are present and match the 'OS/iOS/FW Version' on the HW tab" },
      @{ var = "test100"; name = "Is there a POC identified for Hardware?" },
      @{ var = "test101"; name = "Is there a POA&M for End of Life Hardware inside the authorization boundary?" },
      @{ var = "test102"; name = "Software Type', 'Software Vendor', 'Software Name', and 'Software Version' provided for each software listed" },
      @{ var = "test103"; name = "All Software identified in ACAS scans appear in the Software Baseline" },
      @{ var = "test104"; name = "Is there a POC identified for Software?" },
      @{ var = "test105"; name = "Is there a POA&M for End of Life Software inside the authorization boundary?" }
    )
  },
  @{
    name = "POA&Ms";
    tests = @(
      @{ var = "test106"; name = "POC Information provided under 'General POA&M Information'" },
      @{ var = "test107"; name = "'Point of Contact' information provided in each POA&M record" },
      @{ var = "test108"; name = "All POA&M Entries are mapped to the applicable security control" },
      @{ var = "test109"; name = "POA&M status and control status do not conflict" },
      @{ var = "test110"; name = "'Vulnerability Description' describes vulnerability, except for Not Applicable Control POA&Ms" },
      @{ var = "test111"; name = "Mitigations' entries are specific to the vulnerabilities, reference compliant compensating controls and/or additional protections implemented, and are sufficient to lower the risk of the vulnerability" },
      @{ var = "test112"; name = "Does 'Severity' match NETCOM Risk Analysis guidance for all POA&M records with 'Status' entries of Ongoing and Risk Accepted?" },
      @{ var = "test113"; name = "Does 'Relevance of Threat' match NETCOM Risk Analysis guidance for all POA&M records with 'Status' entries of Ongoing and Risk Accepted?" },
      @{ var = "test114"; name = "Does 'Likelihood' match NETCOM Risk Analysis guidance for all POA&M records with 'Status' entries of Ongoing and Risk Accepted?" },
      @{ var = "test115"; name = "Does 'Impact' match System 'Impact Level' for all POA&M records with 'Status' entries of Ongoing and Risk Accepted?" },
      @{ var = "test116"; name = "'Residual Risk' values match recommended values" },
      @{ var = "test117"; name = "POA&M Risk levels are at or below the high water marks of the Risk Assessment Module. This check is not against the SAR" },
      @{ var = "test118"; name = "POA&M records with 'Status' entries of Ongoing list key events/steps required to close or mitigate the findings as milestones with Scheduled Completion Dates that are realistic and relevant" },
      @{ var = "test119"; name = "POA&M records with 'Status' entries of Ongoing that surpassed milestone completion dates have new milestones with future completion dates and details of why the previous milestones were missed" },
      @{ var = "test120"; name = "Are all expired POA&M's pending an extension?" },
      @{ var = "test121"; name = "'Source Identifying Vulnerability' information provided in POA&M records with 'Status' entries of Ongoing and Risk Accepted" },
      @{ var = "test122"; name = "POA&M items requesting 'Risk Acceptance' have valid justification in 'Recommendations' field" },
      @{ var = "test123"; name = "POA&M records with a 'Status' entry of Completed have evidence to validate vulnerability was closed" },
      @{ var = "test124"; name = "False Positives/False Negatives listed in CM-6.5" },
      @{ var = "test125"; name = "Are STIG checks present that identify no affected assets or checks with no open finding POA&M items? If so, are those POA&Ms marked 'Completed'?" },
      @{ var = "test126"; name = "No new 'Very High' or 'High' Residual Risk has been identified since last authorization" }
    )
  },
  @{
    name = "Artifacts";
    tests = @(
      @{ var = "test127"; name = "Signed Appointment Letters (ISO, O-ISSM & ISSO)" },
      @{ var = "test128"; name = "CONOPs (required for Major Acquisition Programs, ACAT II & III & SIS/CRN)" },
      @{ var = "test129"; name = "PPS List" },
      @{ var = "test130"; name = "Applicable SOPs signed by current appointed authority and reviewed within the last 365 days *must be mapped/linked to the applicable controls/APs/CCIs*" },
      @{ var = "test131"; name = "Are applicable TSP, MOU, MOA or SLA between Mission Owners, customer responsibility matrix (CRM), Cloud Service Provider and Cybersecurity Service Provider attached? *not applicable for cARMY or DISA Hosted Cloud*" },
      @{ var = "test132"; name = "PKI Waiver" },
      @{ var = "test133"; name = "HBSS Waiver" },
      @{ var = "test134"; name = "PIA - Less than 3 years old" },
      @{ var = "test135"; name = "SCA-V/SCA-O SAR *new systems or systems with no previous 3rd party assessment*" },
      @{ var = "test136"; name = "SCA-V/SCA-O Recommendation Memo *new systems or systems with no previous 3rd party assessment*" },
      @{ var = "test137"; name = "SCA-V/SCA-O Assessment Scan Results (ACAS/STIGs) *new systems or systems with no previous 3rd party assessment*" },
      @{ var = "test138"; name = "Self-Assessment Scan Results (ACAS/STIGs)" },
      @{ var = "test139"; name = "All Self-Assessment .ckls are completed per requirements" },
      @{ var = "test140"; name = "Is a Fielding Manual, Deployment Guide or similar artifact available that identifies the receiving unit responsibilities? *may only apply to SIS/CRN systems that are responsible as the CSSP Provider*" }
    )
  },
  @{
    name = "Package";
    tests = @(
      @{ var = "test141"; name = "Does system have a previous NETCOM Control Assessor recommendation or had an independent validation?" },
      @{ var = "test142"; name = "Terms/conditions of previous authorization decision addressed" }
    )
  },
  @{
    name = "Relationships";
    tests = @(
      @{ var = "test143"; name = "Receiving inheritance from 'Army Sentinel CCP' and inheritance DoD Tier1 CCP and Army Tier 2 CCP have been removed?" },
      @{ var = "test144"; name = "Are all applicable inheritance relationships established (e.g., AMC PR, cloud service provider, cArmy, ALTESS, etc.)?" },
      @{ var = "test145"; name = "Are there Controls/CCIs being inherited from the Army Enterprise Cloud CCP and additional provider(s)? Hybrid controls are acceptable." },
      @{ var = "test146"; name = "Are there any CCI's inherited that have an associated STIG? *Exception for Hybrid Controls*" },
      @{ var = "test147"; name = "Are there any critical controls that are being inherited by system from an inheritance relationship that are Non-Compliant? Do the Red Critical POAMs have an effective Mitigation?" },
      @{ var = "test148"; name = "Cybersecurity Service Provider (CSSP) Inheritance established and/or not aligned with cloud service model and data impact level? if applicable" },
      @{ var = "test150"; name = "Manual inheritance established for any control inherited but not captured under a policy record *TSP/MOU/MOA/SLA must document the details/justification for the manual inheritance*" },
      @{ var = "test151"; name = "Documented Associations listed as needed should include any Dependencies listed in APMS" },
      @{ var = "test152"; name = "Documented External Systems listed as needed" }
    )
  },
  @{
    name = "Relationship";
    tests = @(
      @{ var = "test149"; name = "Does the Production cloud system have an established inheritance relationship with C5ISR and does the CSO Impact Level (example IL4, IL5) match the system details? will be added to T&C for IATT & non-prod cloud systems" }
    )
  },
  @{
    name = "Management";
    tests = @(
      @{ var = "test153"; name = "Correct PAC ISO/PM" },
      @{ var = "test154"; name = "Correct PAC O-ISSM" },
      @{ var = "test155"; name = "Correct PAC P-ISSM" },
      @{ var = "test156"; name = "Correct PAC SCA-R" },
      @{ var = "test157"; name = "Correct PAC SCA-A" },
      @{ var = "test158"; name = "Correct PAC AO" },
      @{ var = "test159"; name = "Correct PAC AODR" },
      @{ var = "test160"; name = "Correct PAC Network AO" },
      @{ var = "test161"; name = "Correct PAC Network AODR" },
      @{ var = "test162"; name = "Correct CAC ISO/PM/ISSO" },
      @{ var = "test163"; name = "Correct CAC SCA-V" }
    )
  }
)

# Step 2: Build JSON with results
$final = @{
    systemId = $SystemID
    jobId = $JobID
    elapsedSeconds = $($ElapsedTime.ToString())
    sections = @()
}

foreach ($section in $testSections) {
    $sec = @{
        name = $section.name
        summary = @{ pass = 0; fail = 0; concern = 0; na = 0 }
        tests = @()
    }

    foreach ($test in $section.tests) {
        $var = $test.var
        $result = Get-Variable -Name "$($var)result" -ValueOnly -ErrorAction SilentlyContinue
        if ($result -in @("PASS", "FAIL", "CONCERN", "N/A")) {
            $sec.summary[$result]++
        }
        $sec.tests += @{ name = $test.name; result = $result }
    }
    $final.sections += $sec
}

# Step 3: Output JSON
$final | ConvertTo-Json -Depth 5 | Out-File -FilePath $ResultsJson -Encoding utf8
