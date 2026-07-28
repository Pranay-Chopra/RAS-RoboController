import subprocess


class IWDWiFi:

    @staticmethod
    def scan():

        networks = []

        try:
            result = subprocess.check_output(
                [
                    "iwctl",
                    "station",
                    "wlan0",
                    "get-networks"
                ]
            )

            lines = result.decode().splitlines()

            for line in lines:

                if "ROBOT" in line.upper():

                    ssid = line.strip().split()[0]

                    networks.append(
                        {
                            "ssid": ssid,
                            "rssi": 0
                        }
                    )

        except Exception as e:
            print(e)

        return networks


    @staticmethod
    def connect(robot,password):

        try:

            subprocess.run(
                [
                    "iwctl",
                    "station",
                    "wlan0",
                    "connect",
                    robot.name
                ],
                check=True
            )

            return True


        except Exception as e:

            print(
                "iwd connect failed:",
                e
            )

            return False
