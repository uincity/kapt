﻿
/**
 * 스크롤바 default 옵션 설정
 */
$.extend($.mCustomScrollbar.defaults, {
	scrollButtons : {
		enable : true
	},
	axis : "yx",
	theme : "inset"
});

function getCurrentTime()
{
	var Digital = new Date(); 

	var hours = Digital.getHours(); 
	var minutes = Digital.getMinutes();
	var seconds = Digital.getSeconds();

	if ( hours < 10 )
		hours = "0"+hours;
	if ( minutes < 10 )
		minutes = "0"+minutes;
	if ( seconds < 10 )
		seconds = "0"+seconds;
	

	return (hours+""+minutes+""+seconds);
}

function getEiFile(fileSeq) {
	var frm = document.getElementById('eiFileDownForm');

	frm.action = "/servlets/EiFileDownLoad.do";
	frm.FILE_SEQ.value = fileSeq;
	frm.submit();
}

function cellMergeChk(baseObj, addCellCnt, tableObj, rowIndex, cellIndex)
{
	var rowsCn = tableObj.rows.length;
	if(rowsCn-1 > rowIndex){
		cellMergeProcess(baseObj, addCellCnt, tableObj, rowIndex, cellIndex);
	}
}

function cellMergeProcess(baseObj, addCellCnt, tableObj, rowIndex, cellIndex)
{
	try{
		var parentObj;
		var parentValue;
		var currentParent;
		var rowsCn = tableObj.rows.length;
		var compareCellsLen = baseObj.rows[0].cells.length + addCellCnt;
		
		
		if(cellIndex > 0) parentObj = tableObj.rows[rowIndex].cells[cellIndex-1];
		if(cellIndex > 0) parentValue = parentObj.innerHTML;

		var compareObj = tableObj.rows[rowIndex].cells[cellIndex];
		var compareValue = compareObj.innerHTML;
		var cn = 1;
		var delCells = new Array();
		var arrCellIndex = new Array();
		
		var firstHead = "";
		if(cellIndex > 0){
			firstHead = tableObj.rows[0].cells[cellIndex-1].innerHTML;
		}
		
		for(i=rowIndex+1; i < rowsCn; i++)
		{
			var cellsLen = tableObj.rows[i].cells.length;
			var bufCellIndex = cellIndex;

			if(compareCellsLen != cellsLen) 
			{
				bufCellIndex = bufCellIndex - (compareCellsLen - cellsLen);
				if( bufCellIndex < 0) bufCellIndex = cellIndex;
			}
			cellObj = tableObj.rows[i].cells[bufCellIndex];

			if(cellIndex > 0){ parentObj = tableObj.rows[i].cells[bufCellIndex-1]; }
			if(bufCellIndex > 0){ currentParent = tableObj.rows[i].cells[bufCellIndex-1]; }

			if(compareValue == cellObj.innerHTML && (cellIndex == 0 || (cellIndex != 0 && parentValue == currentParent.innerHTML)))
			{
				delCells[cn-1] = tableObj.rows[i];
				arrCellIndex[cn - 1] = bufCellIndex;
				cn++;
			}
			else
			{
				compareObj.rowSpan = cn;
				
				for(j=0; j < delCells.length; j++)
				{
					delCells[j].deleteCell(arrCellIndex[j]);
				}
				
				compareObj = cellObj;
				compareValue = cellObj.innerHTML;

				if(cellIndex > 0) parentObj = parentObj;
				if(cellIndex > 0) parentValue = parentObj.innerHTML;
				cn = 1;
				delCells = new Array();
				arrCellIndex = new Array();
			}
		}

		compareObj.rowSpan = cn;
		
		for(j=0; j < delCells.length; j++)
		{
			delCells[j].deleteCell(arrCellIndex[j]);
		}
	}catch(e){
	}
}

/**
 * 날짜 포맷 함수
 * @param: date(Date): 날짜
 * @param: patter(String): 년, 월, 일 사이에 들어갈 구분자 
 */
function dateFormat(date, pattern) {
	var result = "";
	try {
		var year = date.getFullYear();
		var month = ( date.getMonth() + 1 );
		var date = date.getDate();
		
		// 월과 일은 10 미만일 경우 0을 붙여준다.
		month = numberLpad( 2, month );
		date = numberLpad( 2, date );
		
		result = [year, month, date].join(pattern);
	}catch (e) {
		console.error(e);
	}
	
	return result;
}

function getNextDay(ymd) {
	ymd = ymd.slice(0, 4) + '-' + ymd.slice(4, 6) + '-' + ymd.slice(6,)
	let d = new Date(ymd)
	d.setDate(d.getDate() + 1)
	
	return dateFormat(d, '');
}

/**
 * 자리수에 맞춰 빈자리 0 채워주는 함수
 * @param: len(int): 길이
 * @param: value(int): 대상 값 
 */
function numberLpad(len, value) {
	if( $.isNumeric(value) ) {
		var valLen = value.toString().length;
		for(i = 0; i < (len - valLen); i++) {
			value = "0" + value;
		}
	}else {
		value = "0";
	}
	return value;
}

/**
 * 날짜를 한국포맷으로 변경하는 함수
 * @param: date(String): 날짜
 * @param: pattern(String): 패턴 - yyyy mm dd
 */
function dateFormatKor(date, pattern, separator) {
	var formatDate = date;
	separator = separator ? separator : '-';
	
	if( date.length == 8 ) {
		if( pattern == "yymmdd" ) {
			formatDate = date.substr(2, 2) + separator + " " + date.substr(4, 2) + separator + " " + date.substr(6, 2);
		}else if( pattern == "mmdd" ) {
			formatDate = date.substr(4, 2) + separator + date.substr(6, 2);
		}else {
			formatDate = date.substr(0, 4) + separator + date.substr(4, 2) + separator + date.substr(6, 2);
		}
	}else if( date.length == 6 ) {
		if( pattern == "mmdd" ) {
			formatDate = date.substr(2, 2) + separator + date.substr(4, 2);
		}else if( pattern == "yyyymm" ) {
			formatDate = date.substr(0, 4) + separator + date.substr(4, 2);
		}else {
			formatDate = date.substr(0, 2) + separator + date.substr(2, 2) + separator + date.substr(4, 2);
		}
	}else if( date.length == 4  && pattern == "mmdd") {
		formatDate = date.substr(0, 2) + separator + date.substr(2, 2);
	}
	
	return formatDate;
}

/**
 * 공시항목 > 인근학교비교 함수
 * @param hg_course_gb
 */
function goJipyo(hg_course_gb){
	$("#goJipyoForm [name=TRANS_DT]").val( $("#select_trans_dt").text() );
	
	if(hg_jongryu_gb == "5") {
		$("#goJipyoForm [name=HG_COURSE_GB]").val( hg_course_gb );
	}else {
		$("#goJipyoForm [name=HG_COURSE_GB]").val( hg_jongryu_gb );
	}
	
	$("#jipyoTableBox").load("<%= contextPath%>/ei/ss/pneiss_a03_s0p.do", $("#goJipyoForm").serializeArray(), function(res, status, xhr) {

		$("#jipyoTableBox").attr('tabindex', -1).focus();
		$("#jipyoTableBox").removeAttr('tabindex');
	});
}

function removeOptions(oSelect)  {
  var count = oSelect.length;
  for(i =0; i < count; i++)	{
    oSelect.remove(0);
  }
  oSelect.setAttribute('selected',0);
}

function makeAjaxPaging(multiPage, pageSize) {
	// desktop
	$(".pagination-desktop").empty();
	$(".pagination-mobile").empty();
	var rowPerPage = multiPage.rowPerPage;
	var totalRowSize = multiPage.totalRowSize;
	var rowSize = multiPage.rowSize;
	var totalPageNumber = Math.floor( ( ( totalRowSize - 1 ) / rowPerPage ) + 1 );
	var pageNumber = multiPage.pageNumber;
	
	var startPage = 0;
	var endPage = 0;
	var ppnumber = 0;
	ppnumber = Math.floor( ( ( pageNumber - 1 ) / pageSize ) );
	startPage = pageSize * ppnumber + 1;
	if( startPage + pageSize - 1 < totalPageNumber ) {
		endPage = startPage + pageSize - 1;
	}else {
		endPage = totalPageNumber;
	}
	if( startPage == 0 && endPage > 0 ) {
		startPage = 1;
	}
	
	var pageHtml = ""; // 웹 페이징
	var mPageHtml = ""; // 모바일 페이징
	if( pageNumber > 1 ) {
		pageHtml += '<a href="javascript:;" onclick="ajaxPageMove(\'1\');return false;" title="첫 페이지" class="pg_arr pg_first"><span>첫 페이지</span></a>';
		mPageHtml += '<a href="javascript:;" onclick="ajaxPageMove(\'1\');return false;" title="첫 페이지" class="pg_arr pg_first"><span>첫 페이지</span></a>';
	}else{
		pageHtml += '<a class="pg_arr pg_first" title="첫 페이지"><span>첫 페이지</span></a>';
		mPageHtml += '<a class="pg_arr pg_first" title="첫 페이지"><span>첫 페이지</span></a>';
	}
	if (pageNumber > 1) {
		pageHtml += '<a href="javascript:;" onclick="ajaxPageMove(\'' + ( pageNumber - 1 ) + '\');return false;" title="이전 페이지" class="pg_arr pg_prev"><span>이전 페이지</span></a>';
		mPageHtml += '<a href="javascript:;" onclick="ajaxPageMove(\'' + ( pageNumber - 1 ) + '\');return false;" title="이전 페이지" class="pg_arr pg_prev"><span>이전 페이지</span></a>';
	}else{
		pageHtml += '<a class="pg_arr pg_prev" title="이전 페이지"><span>이전 페이지</span></a>'; 
		mPageHtml += '<a class="pg_arr pg_prev" title="이전 페이지"><span>이전 페이지</span></a>'; 
	}
	
	for(var i = startPage; startPage > 0 && i <= endPage; i++) {
		if(i == pageNumber) {
			pageHtml += '<a href="javascript:;" title="현재페이지" class="pg_a pg_active" aria-current="page">' + i + '</a>';
		}else {
			pageHtml += '<a class="pg_a" href="javascript:;" onclick="ajaxPageMove(\'' + i + '\');return false;" title="' + i + '페이지 이동">' + i + '</a>';
		}
	}
	
	mPageHtml += '<a title="현재페이지" class="pg_now" aria-current="page">' + pageNumber + '/' + endPage + '</a>';
	
	if (pageNumber < totalPageNumber) {
		pageHtml += '<a href="javascript:;" onclick="ajaxPageMove(\'' + ( pageNumber + 1 ) + '\');return false;" title="다음 페이지" class="pg_arr pg_next"><span>다음 페이지</span></a>';
		mPageHtml += '<a href="javascript:;" onclick="ajaxPageMove(\'' + ( pageNumber + 1 ) + '\');return false;" title="다음 페이지" class="pg_arr pg_next"><span>다음 페이지</span></a>';
	}else{
		pageHtml += '<a class="pg_arr pg_next" title="다음 페이지"><span>다음 페이지</span></a>';
		mPageHtml += '<a class="pg_arr pg_next" title="다음 페이지"><span>다음 페이지</span></a>';
	}
	if ( pageNumber < totalPageNumber ) {
		pageHtml += '<a href="javascript:;" onclick="ajaxPageMove(\'' + totalPageNumber + '\');return false;" title="마지막 페이지" class="pg_arr pg_last"><span>마지막 페이지</span></a>';
		mPageHtml += '<a href="javascript:;" onclick="ajaxPageMove(\'' + totalPageNumber + '\');return false;" title="마지막 페이지" class="pg_arr pg_last"><span>마지막 페이지</span></a>';
	}else{
		pageHtml += '<a class="pg_arr pg_last" title="마지막 페이지"> <span>마지막 페이지</span> </a>';
		mPageHtml += '<a class="pg_arr pg_last" title="마지막 페이지"> <span>마지막 페이지</span> </a>';
	}
	 
	$(".pagination-desktop").append(pageHtml);
	$(".pagination-mobile").append(mPageHtml);
	
}

/**
 * 요일가져오기
 */
function getDayName(date) {
	var d = new Date(date);
	var day = d.getDay();
	var dayName;
	switch(day){
		case 0:
			dayName='일'
			break;
		case 1:
			dayName='월'
			break;
		case 2:
			dayName='화'
			break;
		case 3:
			dayName='수'
			break;
		case 4:
			dayName='목'
			break;
		case 5:
			dayName='금'
			break;
		case 6:
			dayName='토'
			break;
	}
	return dayName;
}

/**
 * IOS 웹뷰인지 확인
 */
function isIOSWebView(){
	var userAgent = navigator.userAgent || navigator.vendor || window.opera;
	var isIOS = /iPad|iPhone|iPod/.test(userAgent) && !window.MSStream;
	var isSafari = /^((?!chrome|android).)*safari/i.test(userAgent);
	
	return isIOS && !isSafari;
}

/**
 * 안드로이드 웹뷰인지 확인
 */
function isAndroidWebView(){
	var userAgent = navigator.userAgent || navigator.vendor || window.opera;
	
	return /wv/.test(userAgent) || /Android/.test(userAgent) && !/Chrome\/[.0-9]* Mobile/.test(userAgent);
}

/**
 * 힌트 이미지 클릭 시 삭제
 */
$(document).on('click', '.KeduImg', function(){
	$(this).remove();
})

/*
// 우클릭 방지
document.oncontextmenu = function(){return false;}

// ctrl + shift + i, f12, ctrl + shift + j, ctrl + u 차단
document.addEventListener('keydown', function (event){
	if (event.key === 'F12' || (event.ctrlKey && event.shiftKey && event.key === 'I') || (event.ctrlKey && event.shiftKey && event.key === 'J')
	   || (event.ctrlKey && event.shiftKey && event.key === 'C') || (event.ctrlKey && event.key === "U") || (event.ctrlKey && event.key === "u")) {
		event.preventDefault();
	}	
})
*/

