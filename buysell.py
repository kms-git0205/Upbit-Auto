import pyupbit
import os
import jwt
import uuid
import hashlib
from urllib.parse import urlencode
import time

import requests

# 전역변수 선언
buy_price = 10000  # 매수 가격 지정
log_file = "./buy_sell_log.txt"  # 로그 기록할 파일 경로
#key.txt에 키 알맞게 저장해 주어야 함

def log_write(str):  # 로그 파일에 기록
    now = time.localtime()
    cur_time = "[%04d/%02d/%02d %02d:%02d:%02d] " % (
        now.tm_year, now.tm_mon, now.tm_mday, now.tm_hour, now.tm_min, now.tm_sec)
    with open(log_file, 'a') as f: f.writelines(cur_time + str + '\n\n')
    print(cur_time + str + '\n\n', end=' ')



log_write('ATS start')

f = open("./key.txt")
lines = f.readlines()
access_key = lines[1].strip()  # access key
secret_key = lines[3].strip()  # secret key
server_url = 'https://api.upbit.com'  # server url
f.close()
upbit = pyupbit.Upbit(access_key, secret_key)

coin_list = []  # 내가 보유한 코인 이름 리스트
coin_avgbuy_list = {}  # 보유한 코인 : 평단가를 저장한 딕셔너리
sell_limit_list = {}  # 보유한 코인 : 최소 매도 가격을 저장한 딕셔너리


def show():  # 현 상황을 출력
    str = "\n-------------------------------------------------------------------------------------------------------------------------\n"
    str += "|" + "보유코인".center(18, ' ') + "\t|" + "평단가".center(20, ' ') + "\t|" + "현재가".center(20, ' ') + "\t|" + "매도 한도".center(18, ' ') + "\t|" + "현재 수익률(%)".center(18, ' ') + '\t|\n'
    str += "-------------------------------------------------------------------------------------------------------------------------\n"
    for coin in coin_list:
        avgbuy = coin_avgbuy_list[coin] # 평단가
        time.sleep(0.1)
        curprice = pyupbit.get_current_price(coin)  #현재가
        earning = "%.2f" % ((curprice / avgbuy - 1.0) * 100) # 수익률
        str+= "|" + coin.center(20, ' ') + "\t|" + repr(avgbuy).center(22, ' ') +"\t|" + repr(curprice).center(22, ' ') + "\t|" + repr(sell_limit_list[coin]).center(22, ' ') + "\t|" + repr(earning+' %').center(22, ' ') + "\t|\n"

        str += "-------------------------------------------------------------------------------------------------------------------------\n"

    log_write(str)

def get_all_coins():  # 모든 코인 리스트 반환
    url = "https://api.upbit.com/v1/market/all"
    querystring = {"isDetails": "false"}
    headers = {"Accept": "application/json"}
    response = requests.request("GET", url, headers=headers, params=querystring).json()

    list = []
    for i in range(len(response)):
        check = response[i]['market']
        if 'KRW-' in check:
            list.append(check)
    return list


def load_my_account():  # 내 보유 자산 불러오기 -> 보유 코인 리스트 갱신, 평단가 리스트 갱신, 매도한도가격 리스트 갱신

    global coin_avgbuy_list
    global sell_limit_list
    global coin_list

    payload = {
        'access_key': access_key,
        'nonce': str(uuid.uuid4()),
    }

    jwt_token = jwt.encode(payload, secret_key)
    authorize_token = 'Bearer {}'.format(jwt_token)
    headers = {"Authorization": authorize_token}
    res = requests.get(server_url + "/v1/accounts", headers=headers).json()

    coin_avgbuy_list = {}
    coin_list = []

    for i in range(1, len(res)):
        coin_avgbuy_list['KRW-' + res[i]['currency']] = float(res[i]['avg_buy_price'])
        coin_list.append('KRW-' + res[i]['currency'])
    time.sleep(0.1)
    set_sell_limit()  # 매도한도 갱신은 따로 함수를 만듬
    show()


def check_candle(type, coin, count, num):  # coin의 봉 count개 확인 -> 최근 봉이 모두 상승인지(일/주/월 봉에 따라 3/2/1개 확인)
    url = "https://api.upbit.com/v1/candles/" + type  # type에 따라 일/주/월/분봉 결정
    querystring = {"market": coin, "count": count}
    headers = {"Accept": "application/json"}
    response = requests.get(url=url, headers=headers, params=querystring).json()

    for i in range(len(response)):

        if num == 1:
            if float(response[i]['trade_price']) - float(response[i]['opening_price']) <= 0:  # 일봉이 하락인 경우, False 리턴
                return False
        else:  # num==2 -> 하락봉 연속 3개를 확인할 때
            if float(response[i]['trade_price']) - float(response[i]['opening_price']) >= 0:  # 일봉이 상승인 경우, False 리턴
                return False
    return True


def check_buy(coin):  # 특정 코인의 매수 조건 충족여부를 반환
    if upbit.get_balance(coin) != 0: return False  # 이미 매수한 코인인지
    if upbit.get_balance("KRW") < buy_price: return False  # 잔고 확인
 
    # 일/주/월 봉 확인 + 분봉 확인(1분)
    if check_candle("minutes/1", coin, 3, 1) is False: return False
    if check_candle("days", coin, 3, 1) is False: return False
    if check_candle("weeks", coin, 1, 1) is False: return False
    if check_candle("months", coin, 1, 1) is False: return False

    # True 리턴할 경우에만 상황 출력 -> 매수가 일어나는 경우임
    log_write(coin + "의 보유 잔고 : " + str(upbit.get_balance(coin)) + "\n현금 확인 : " + str(upbit.get_balance("KRW")) +
              " \n일/주/월/분봉(1분) 확인 : " + str(
        check_candle("days", coin, 3, 1)) + "/" + str(check_candle("weeks", coin, 2, 1)) + "/" + str(
        check_candle("months", coin, 1, 1)) + "/" + str(check_candle("minutes/1", coin, 3, 1)))
    return True


def buy(coin, price):  # 코인 매수 구현
    print('buy 들어옴')
    tmpstr = upbit.buy_market_order(coin, price)  # 시장가 주문 -> coin을 price가격만큼 매수
    log_write(str(tmpstr))
    load_my_account()


def set_sell_limit():  # 보유한 코인들의 매도 최소가격을 갱신
    i = 0
    global coin_avgbuy_list
    global sell_limit_list
    global coin_list
    for coin in coin_list:

        if coin not in sell_limit_list.keys():  # 보유코인, 매도한도 목록 동기화(새로 산 코인 더하기)
            sell_limit_list[coin] = float(coin_avgbuy_list[coin]) * 0.95    #최대 5% 손실 설정
        time.sleep(0.1)
        cur_price = float(pyupbit.get_current_price(coin))  # 현재가격
        tmp = 0

        if cur_price < float(coin_avgbuy_list[coin]) * 1.02:  # 수익률 2% 이하의 경우 -> 5%까지 손실 가능
            tmp = float(coin_avgbuy_list[coin]) * 0.95
       # elif cur_price < float(coin_avgbuy_list[coin]) * 1.10:  # 수익률 10%이하의 경우
       #     tmp = float(coin_avgbuy_list[coin]) * 1.02
        else:
            tmp = (float(coin_avgbuy_list[coin]) + cur_price) / 2  # 평단가의 102%가 넘어가면 -> (평단가 + 현재가) / 2 로 지정
        # tmp값이 기존 매도한도보다 클 때만 갱신 -> 매도한도가 내려가지는 않음
        if float(sell_limit_list[coin]) < tmp:
            sell_limit_list[coin] = tmp
        i += 1


def check_sell(coin):  # 특정 코인의 매도 조건 충족여부를 반환(매도한도 도달 확인은 따로 구현)

    if upbit.get_balance(coin) == 0: return False  # 가지고 있는 코인인지

    # 일/주/월 봉 확인
    if check_candle("days", coin, 3, 2) is False: return False
    if check_candle("weeks", coin, 1, 2) is False: return False
    if check_candle("months", coin, 1, 2) is False: return False

    # True 리턴할 경우에만 상황 출력 -> 매도가 일어나는 경우임
    log_write(coin + "의 보유 잔고 : " + str(upbit.get_balance(coin)) + " \n일/주/월봉 확인 : " + str(
        check_candle("days", coin, 3, 2)) + "/" + str(check_candle("weeks", coin, 2, 2)) + "/" + str(
        check_candle("months", coin, 1, 2)))
    return True


def sell(coin):  # 해당 코인 전량 시장가 매도
    tmpstr = upbit.sell_market_order(coin, upbit.get_balance(coin))
    log_write(str(tmpstr))
    del sell_limit_list[coin]  # 매도한 코인 매도한도 딕셔너리에서 삭제
    load_my_account()


def sell_cycle():  # 매도 사이클 1번
    log_write("매도 판단 중")
    # 매도한도 이하 가격인 코인 매도
    set_sell_limit()
    for coin in coin_list:
        time.sleep(0.1)  # get_current_price()가 한꺼번에 몰리니까 nonetype 반환했음 -> 간격을 설정
        get_cur_price = pyupbit.get_current_price(coin)
        if float(get_cur_price) < sell_limit_list[coin]:
            log_write(coin + " 매도한도 이하이므로 전량매도 -> " + str(get_cur_price) + " < " + str(sell_limit_list[coin]))
            sell(coin)

    # 3일연속 하락한 코인 매도
    '''
    for coin in coin_list:
        time.sleep(0.1)
        if check_sell(coin):
            log_write(coin + "3일연속 하락이므로 전량매도")
           # sell(coin)
    '''
    log_write("매도 완료")
    load_my_account()

def buy_cycle():  # 매수 사이클 1번
    log_write("매수 판단 중")

    for coin in all_coins:
        if check_buy(coin):
            log_write(coin + "구매 -> " + str(buy_price))
            buy(coin, buy_price)  # 여기 매수 구현


    # 모든 코인에 대해 매수 조건 확인 해서 진행 -> 20초정도 걸림

    log_write("매수 완료")
    load_my_account()  # coin_list, coin_avgbuy_list 갱신, sell_limit_list 갱신


all_coins = get_all_coins()  # 모든 코인 리스트
load_my_account()

# main start
while True:
    try:
        time.sleep(1)
        buy_cycle()
        time.sleep(1)
        sell_cycle()
    except Exception as e:
        log_write('오류 발생 -> ' + str(e))

