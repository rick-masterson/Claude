import QtQuick 2.15

Rectangle {
    id: root
    color: "#000000"
    property int stage: 0
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#00000000" }
            GradientStop { position: 1.0; color: "#AA000000" }
        }
    }
    Text {
        anchors.centerIn: parent
        text: "stage " + root.stage
        color: "#c084fc"
        font.letterSpacing: 2
    }
}
