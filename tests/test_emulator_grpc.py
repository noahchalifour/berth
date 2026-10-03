from emulator_hub._grpc import emulator_controller_pb2 as pb
from emulator_hub.emulator_grpc import GrpcScreen


class RecordingStub:
    def __init__(self):
        self.keys = []

    async def sendKey(self, event):
        self.keys.append(event)


async def test_key_is_a_full_press_not_a_held_key():
    screen = GrpcScreen.__new__(GrpcScreen)
    screen._stub = RecordingStub()
    await screen.key("Enter")
    [event] = screen._stub.keys
    assert event.key == "Enter"
    # The proto default is keydown: Android would auto-repeat it.
    assert event.eventType == pb.KeyboardEvent.keypress
