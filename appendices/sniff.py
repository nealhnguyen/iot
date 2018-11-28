import socket, struct, sys
from scapy.all import ETH_P_ALL
from scapy.all import MTU
import time
import datetime
import MySQLdb as sql
from multiprocessing import Process
import pywemo
import binascii
import hexdump


try:
    db = sql.connect("ciscoiot3.cdfsxn4jreun.us-west-2.rds.amazonaws.com",
    "cisco", "ciscoIOT985", "ip_log", read_default_file='/etc/mysql/my.cnf')
    db.ping(True)
except:
    sys.exit("Couldn't connect to database")

try:
    db1 = sql.connect("ciscoiot3.cdfsxn4jreun.us-west-2.rds.amazonaws.com",
    "cisco", "ciscoIOT985", "ip_log", read_default_file='/etc/mysql/my.cnf')
    db1.ping(True)
except:
    sys.exit("Couldn't connect to database")


proto = {num:name[8:] for name,num in vars(socket).items() if
        name.startswith("IPPROTO")}

class IPSniff:

    def __init__(self, interface_name, incoming_ip, outgoing_ip, cursor):

        self.interface_name = interface_name
        self.incoming_ip = incoming_ip
        self.outgoing_ip = outgoing_ip

        # Open a socket to read traffic from 
        self.socket = socket.socket(
            socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2**30)
        self.socket.bind((self.interface_name, ETH_P_ALL))


    def __process_ipframe(self, packet, pkt_type, ip_header, payload, cursor):

        # Extract the IP header
        version = (ip_header[0] & 0xf0) >> 4
        if version == 4:
            fields = struct.unpack("!BBHHHBBHII", ip_header)
            total_length = fields[2]
            src_ip = payload[12:16]
            dst_ip = payload[16:20]
        elif version == 6:
            fields = struct.unpack("!BBHHBBQQQQ", ip_header)
            total_length = fields[4] + 40
            src_ip = payload[8:24]
            dst_ip = payload[24:40]

        dummy_hdrlen = fields[0] & 0xf

        ip_frame = payload[0:total_length]

        if pkt_type == socket.PACKET_OUTGOING:
            if self.outgoing_ip is not None:
                self.outgoing_ip(src_ip, dst_ip, ip_frame, cursor, packet)

        else:
            if self.incoming_ip is not None:
                self.incoming_ip(src_ip, dst_ip, ip_frame, cursor, packet)


    def recv(self, cursor):
        ipv4 = 0x0800
        ipv6 = 0x86dd
        belkin_mac = ['ec:1a:59', '14:91:82']
        while True:

            packet, address = self.socket.recvfrom(MTU)

            if type == socket.PACKET_OUTGOING and self.outgoing_ip is None:
                continue
            elif self.outgoing_ip is None:
                continue

            if len(packet) <= 0:
                break
         
            eth_header = struct.unpack("!6s6sH", packet[0:14])
            src = ':'.join(format(a, '02x') for a in
            bytes.fromhex(binascii.hexlify(eth_header[0]).decode('utf-8')))
            dst = ':'.join(format(a, '02x') for a in
            bytes.fromhex(binascii.hexlify(eth_header[1]).decode('utf-8')))
            if not any(i in src or i in dst for i in belkin_mac) or '-w' in sys.argv:
                # Ignore non IP Packets
                if eth_header[2] != ipv4 and eth_header[2] != ipv6:
                    continue
                if eth_header[2] == ipv4:
                    ip_header = packet[14:34]
                elif eth_header[2] == ipv6:
                    ip_header = packet[14:54]
                payload = packet[14:]

                self.__process_ipframe(packet, address[2], ip_header, payload, cursor)


def incoming_packet(src, dst, frame, cursor, packet):
    src_port, dst_port = 0, 0
    version = (frame[0] & 0xf0) >> 4

    if version == 4:
        start = 20
        end = 24
        family = socket.AF_INET
        pro = 9
    else:
        start = 40
        end = 44
        family = socket.AF_INET6
        pro = 6

    try:
        if proto[frame[pro]] in ['TCP', 'UDP']:
            ports = struct.unpack("!HH", frame[start:end])
            src_port = ports[0]
            dst_port = ports[1]
    except KeyError:
        pass
    if src_port == 53 or dst_port == 53:
        return

    try:
        src_hostname = socket.gethostbyaddr(socket.inet_ntop(family, src))[0]
    except socket.herror:
        src_hostname = "N/A"
    try:
        dst_hostname = socket.gethostbyaddr(socket.inet_ntop(family, dst))[0]
    except socket.herror:
        dst_hostname = "N/A"
    try:
        protocol = proto[frame[pro]]
    except KeyError:
        protocol = frame[pro]

    try:
        h = hexdump.hexdump(packet, result='return')
        if '-v' in sys.argv:
            print("incoming - src=%s (%s), dst=%s (%s), protocol=%s frame len = %d time= %s source port = %s dest port = %s"
                %(socket.inet_ntop(family, src), src_hostname, socket.inet_ntop(family, dst), dst_hostname, proto[frame[pro]], len(frame),
                time.ctime(), src_port, dst_port))

        cursor.execute("""INSERT INTO ip (source, destination, time, size, type, protocol, src_port, dst_port, src_host, dst_host, hexdump)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);""", (socket.inet_ntop(family, src), socket.inet_ntop(family, dst),
        datetime.datetime.now().isoformat(),len(frame), 'incoming', protocol, src_port, dst_port, src_hostname, dst_hostname,
        h))
        db.commit()
    except:
        print("--------------------------------------------------------------------------------------------")
        print(len("INSERT INTO ip (source, destination, time, size, type, protocol, src_port, dst_port, src_host, dst_host, hexdump) VALUES ({}, {}, {}, {}, {}, {}, {}, {}, {}, {},{});".format(socket.inet_ntop(family, src), socket.inet_ntop(family, dst), datetime.datetime.now().isoformat(),len(frame), 'outgoing', protocol, src_port, dst_port, src_hostname, dst_hostname,h)))
        print("Unexpected error:", sys.exc_info()[0])
        pass


def outgoing_packet(src, dst, frame, cursor, packet):
    src_port, dst_port = 0, 0
    version = (frame[0] & 0xf0) >> 4
    if version == 4:
        start = 20
        end = 24
        family = socket.AF_INET
        pro = 9
    else:
        start = 40
        end = 44
        family = socket.AF_INET6
        pro = 6
    try:
        if proto[frame[pro]] in ['TCP', 'UDP']:
            ports = struct.unpack("!HH", frame[start:end])
            src_port = ports[0]
            dst_port = ports[1]
    except KeyError:
        pass

    if src_port == 53 or dst_port == 53:
        return
    try:
       src_hostname = socket.gethostbyaddr(socket.inet_ntop(family, src))[0]
    except socket.herror:
        src_hostname = "N/A"
    try:
        dst_hostname = socket.gethostbyaddr(socket.inet_ntop(family, dst))[0]
    except socket.herror:
        dst_hostname = "N/A"

    try:
        protocol = proto[frame[pro]]
    except KeyError:
        protocol = frame[pro]

    try:
        h = hexdump.hexdump(packet, result='return')
        if '-v' in sys.argv:
            print("outgoing - src=%s (%s), dst=%s (%s), protocol=%s frame len = %d time= %s source port = %s dest port = %s"
            %(socket.inet_ntop(family, src), src_hostname, socket.inet_ntop(family, dst), dst_hostname, proto[frame[pro]], len(frame),time.ctime(), src_port, dst_port))

        cursor.execute("""INSERT INTO ip (source, destination, time, size, type, protocol, src_port, dst_port, src_host, dst_host, hexdump)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);""", (socket.inet_ntop(family, src), socket.inet_ntop(family, dst),
        datetime.datetime.now().isoformat(),len(frame), 'outgoing', protocol, src_port, dst_port, src_hostname, dst_hostname,
        h))
        db.commit()
    except:
        print("---------------------------------------------------------------------------------------")
        print(len("INSERT INTO ip (source, destination, time, size, type, protocol, src_port, dst_port, src_host, dst_host, hexdump) VALUES ({}, {}, {}, {}, {}, {}, {}, {}, {}, {},{});".format(socket.inet_ntop(family, src), socket.inet_ntop(family, dst), datetime.datetime.now().isoformat(),len(frame), 'outgoing', protocol, src_port, dst_port, src_hostname, dst_hostname,h)))
        print("Unexpected error:", sys.exc_info()[0])


def scan_until_all_found():
    print("Discovering Wemos")
    switches = pywemo.discover_devices()
    print("Discovered {} switches".format(len(switches)))
    print(switches)
    try_num = 1

    while len(switches) < 15:
        print("Did not discover enough switches, trying again{}...".format(try_num))
        switches = pywemo.discover_devices()
        try_num += 1
        print("Discovered {} switches".format(len(switches)))

    return switches


def monitor_power(cursor):
    switches = scan_until_all_found()

    while True:
        for insight in switches:
            if insight is not None:
                try:
                    insight.update_insight_params()
                except AttributeError:
                    print("For Insight", insight)
                    print("Insight params was none", sys.exc_info()[0])
                    switches = scan_until_all_found()
                    break
                power = insight.current_power
                today_kwh = insight.today_kwh
                on_for = insight.on_for
                today_on_time = insight.today_on_time

                if '-p' in sys.argv:
                    print(insight, power, 'mW', today_kwh, on_for, today_on_time)
                try:
                    cursor.execute("""INSERT INTO power (name, power_mw, time,
                    today_kwh, on_for, today_on_time)
                    VALUES (%s, %s, %s, %s, %s, %s);""", (insight.name, power,
                    datetime.datetime.now().isoformat(), today_kwh, on_for,
                    today_on_time))
                    db1.commit()
                except:
                    print("Power error:", sys.exc_info()[0])
        time.sleep(1)


def main():
    cursor = db.cursor()
    cursor1 = db1.cursor()
    ip_sniff = IPSniff(sys.argv[1], outgoing_packet, incoming_packet, cursor)

    p1 = Process(target=ip_sniff.recv, args=(cursor,))
    p1.start()
    p2 = Process(target=monitor_power, args=(cursor1,))
    p2.start()

    p1.join()
    p2.join()


if __name__ == "__main__":
    main()