import QtQuick 2.15

Rectangle {
    id: root
    color: "#000000"
    property int stage: 0
    Text {
        anchors.centerIn: parent
        text: "broken"
        letterSpacing: 2
    }
}
